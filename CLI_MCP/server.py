import asyncio
import json
import sys
import os
import re
import time
import hashlib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from openai import OpenAI
from contextlib import AsyncExitStack

from mcp_client import MCPClient
from core.tools import ToolManager
from mcp.types import TextContent


# ── Config ────────────────────────────────────────────────────────────────────
LLAMA_CPP_URL    = "http://127.0.0.1:8080/v1"
MODEL            = "qwen3"
MAX_TOKENS       = 1024
CTX_LIMIT        = 8192          # matches your -c 8192
CTX_SAFETY       = 0.80
MAX_PROMPT_CHARS = int(CTX_LIMIT * CTX_SAFETY * 3.5)
TOOL_RESULT_CAP  = 800
MAX_ITERATIONS   = 10


# ════════════════════════════════════════════════════════════════════════════
#  QUERY CLASSIFIER  — pure Python, zero LLM tokens spent on routing
# ════════════════════════════════════════════════════════════════════════════

# Requires live / real-time data
_LIVE_RE = re.compile(
    r"\b("
    r"weather|forecast|temperature|rain|snow|wind|humidity|"
    r"current|now|today|tonight|live|latest|recent|right now|"
    r"this (week|month|year)|as of|ongoing|breaking|"
    r"price|stock|crypto|score|match|game|news|trend|"
    r"search (for)?|look up|find out"
    r")\b",
    re.IGNORECASE,
)

# Pure knowledge — answerable from training
_KNOWLEDGE_RE = re.compile(
    r"^("
    r"hi+[!?.]?|hello+[!?.]?|hey+[!?.]?|howdy|yo+|sup|"
    r"good\s?(morning|afternoon|evening|night)|"
    r"how are you|what('s| is) up|nice to meet|"
    r"thanks?[!?.]?|thank you[!?.]?|ok[!?.]?|okay[!?.]?|"
    r"sure[!?.]?|great[!?.]?|cool[!?.]?|awesome[!?.]?|"
    r"bye[!?.]?|goodbye[!?.]?|see you[!?.]?|cya[!?.]?|"
    r"what (is|are|was|were|does|do|did|means?|mean) .{1,80}|"
    r"(explain|describe|define|tell me about|how does|how do|"
    r"why (is|are|does|do)|who (is|was|are|were)|"
    r"when (was|did|is)|where (is|was)|which (is|are)) .{1,80}"
    r")$",
    re.IGNORECASE,
)

class QueryMode:
    NO_TOOLS   = "no_tools"
    WITH_TOOLS = "with_tools"

def classify(query: str) -> QueryMode:
    q = query.strip()
    if _LIVE_RE.search(q):
        return QueryMode.WITH_TOOLS
    if _KNOWLEDGE_RE.match(q) or len(q) <= 30:
        return QueryMode.NO_TOOLS
    return QueryMode.NO_TOOLS   # safe default


# ── Time helpers ──────────────────────────────────────────────────────────────
_TIME_RE = re.compile(
    r"\b(current|now|today|tonight|live|latest|recent|right now|"
    r"this (week|month|year)|at the moment|as of|ongoing|"
    r"present(ly)?|real[-\s]?time|up[-\s]?to[-\s]?date)\b",
    re.IGNORECASE,
)
_WEATHER_RE = re.compile(
    r"\b(weather|forecast|rain|snow|wind|humidity|feels like|temperature)\b",
    re.IGNORECASE,
)

def needs_time_context(query: str) -> bool:
    return bool(_TIME_RE.search(query)) or bool(_WEATHER_RE.search(query))

def build_time_context() -> str:
    now_utc = datetime.now(timezone.utc)
    tz_name = os.getenv("LOCAL_TZ", "UTC")
    try:
        now_local = now_utc.astimezone(ZoneInfo(tz_name))
    except Exception:
        now_local, tz_name = now_utc, "UTC"
    return (
        f"\n⏰ NOW: {now_utc.strftime('%A %d %B %Y %H:%M UTC')} | "
        f"Local ({tz_name}): {now_local.strftime('%H:%M')}\n"
    )


# ── System prompts ────────────────────────────────────────────────────────────
_SYSTEM_CHAT = (
    "You are Aria, a concise professional AI assistant. "
    "Answer clearly. Use markdown when it adds value. "
    "Never make up facts."
)

def build_system_tools(injected: str = "") -> str:
    return (
        f"You are Aria, a concise professional AI assistant.\n{injected}\n"
        "Use tools ONLY for live/current data (weather, news, prices, time). "
        "Never call a tool for general knowledge. "
        "Never repeat a tool call with identical arguments. "
        "Answer concisely using markdown when helpful."
    )


# ── LLM client ────────────────────────────────────────────────────────────────
llm = OpenAI(base_url=LLAMA_CPP_URL, api_key="not-needed")

def chat(messages: list, tools=None):
    params: dict = {
        "model":       MODEL,
        "messages":    trim_messages(messages),
        "temperature": 0.2,
        "max_tokens":  MAX_TOKENS,
    }
    if tools:
        params["tools"]       = tools
        params["tool_choice"] = "auto"
    return llm.chat.completions.create(**params)


# ── Context trimmer ───────────────────────────────────────────────────────────
def estimate_chars(messages: list) -> int:
    return sum(
        len(json.dumps(m.get("content") or "")) +
        len(json.dumps(m.get("tool_calls") or ""))
        for m in messages
    )

def trim_messages(messages: list) -> list:
    if estimate_chars(messages) <= MAX_PROMPT_CHARS:
        return messages
    head = messages[:2]
    tail = messages[2:]
    while tail and estimate_chars(head + tail) > MAX_PROMPT_CHARS:
        dropped = False
        for i, m in enumerate(tail):
            if m.get("role") == "assistant" and m.get("tool_calls"):
                j = i + 1
                while j < len(tail) and tail[j].get("role") == "tool":
                    j += 1
                tail = tail[j:]
                dropped = True
                break
        if not dropped:
            break
    trimmed = head + tail
    print(f"  ✂️  Context trimmed → {estimate_chars(trimmed):,} chars")
    return trimmed


# ── Tool registry ─────────────────────────────────────────────────────────────
class ToolRegistry:
    def __init__(self):
        self._map: dict[str, object] = {}

    async def build(self, clients: dict):
        for client in clients.values():
            for t in await client.list_tools():
                self._map[t.name] = client
        print(f"  📋 Registry: {len(self._map)} tools indexed")

    def client_for(self, name: str):
        return self._map.get(name)


# ── Call dedup (per turn) ─────────────────────────────────────────────────────
class CallDedup:
    def __init__(self):
        self._seen: set[str] = set()

    def _key(self, name: str, args: dict) -> str:
        return f"{name}::{hashlib.md5(json.dumps(args, sort_keys=True).encode()).hexdigest()}"

    def seen(self, name: str, args: dict) -> bool:
        return self._key(name, args) in self._seen

    def mark(self, name: str, args: dict):
        self._seen.add(self._key(name, args))


# ── Execute one tool call ─────────────────────────────────────────────────────
async def execute_tool(tc, registry: ToolRegistry, dedup: CallDedup):
    tool_name = tc.function.name
    tool_id   = tc.id

    try:
        tool_input = json.loads(tc.function.arguments)
    except Exception:
        tool_input = {}

    if dedup.seen(tool_name, tool_input):
        note = f"[duplicate {tool_name} skipped]"
        print(f"  ⚠️  {note}")
        return tool_id, json.dumps({"note": note})
    dedup.mark(tool_name, tool_input)

    print(f"  🔧 [{tool_name}]  {json.dumps(tool_input)}")

    client = registry.client_for(tool_name)
    if client is None:
        err = json.dumps({"error": f"tool '{tool_name}' not found"})
        print(f"  ❌ {err}")
        return tool_id, err

    try:
        output  = await client.call_tool(tool_name, tool_input)
        texts   = [i.text for i in output.content if isinstance(i, TextContent)]
        full    = json.dumps(texts)
        stored  = full[:TOOL_RESULT_CAP] + ("…[truncated]" if len(full) > TOOL_RESULT_CAP else "")
        preview = stored[:140].replace("\n", " ")
        print(f"  ✅ {preview}{'…' if len(stored) > 140 else ''}")
        return tool_id, stored
    except Exception as e:
        err = json.dumps({"error": str(e)})
        print(f"  ❌ {e}")
        return tool_id, err


# ── No-tools path ─────────────────────────────────────────────────────────────
async def run_no_tools(query: str) -> str:
    resp = chat([
        {"role": "system", "content": _SYSTEM_CHAT},
        {"role": "user",   "content": query},
    ])
    return resp.choices[0].message.content or ""


# ── With-tools path ───────────────────────────────────────────────────────────
async def run_with_tools(query: str, tools: list, registry: ToolRegistry) -> str:
    injected = build_time_context() if needs_time_context(query) else ""
    messages: list[dict] = [
        {"role": "system", "content": build_system_tools(injected)},
        {"role": "user",   "content": query},
    ]
    dedup = CallDedup()

    for iteration in range(1, MAX_ITERATIONS + 1):
        resp = chat(messages, tools=tools)
        msg  = resp.choices[0].message
        raw  = msg.content or ""

        if not msg.tool_calls:
            return raw

        print(f"\n  ⚙️  Round {iteration} — {len(msg.tool_calls)} call(s)")

        messages.append({
            "role":       "assistant",
            "content":    raw,
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ],
        })

        results = await asyncio.gather(
            *[execute_tool(tc, registry, dedup) for tc in msg.tool_calls]
        )
        for tid, result in results:
            messages.append({"role": "tool", "tool_call_id": tid, "content": result})

    # Fallback
    print("\n⚠️  Max iterations — forcing final answer")
    messages.append({"role": "user", "content": "Give your final answer now. No more tool calls."})
    return (chat(messages).choices[0].message.content or "")


# ── Unified entry ─────────────────────────────────────────────────────────────
async def run(query: str, tools: list, registry: ToolRegistry) -> tuple[str, str]:
    mode = classify(query)
    if mode == QueryMode.NO_TOOLS:
        return await run_no_tools(query), "🧠 direct"
    return await run_with_tools(query, tools, registry), "🔧 tools"


# ── Pretty printer ────────────────────────────────────────────────────────────
def print_answer(text: str, label: str):
    w = 72
    print("\n" + "═"*w + f"\n  🤖  ARIA  [{label}]\n" + "═"*w)
    print(text)
    print("═"*w)


# ── CLI ───────────────────────────────────────────────────────────────────────
BANNER = """\
╔══════════════════════════════════════════════════════════════════╗
║                    🤖  A R I A  v2.6                            ║
║     Smart Autonomous AI  ·  {model:<36}║
╚══════════════════════════════════════════════════════════════════╝
  Commands: exit | quit | clear
"""

async def main():
    command = "uv" if os.getenv("USE_UV", "0") == "1" else "python"
    args    = ["run", "mcp_server.py"] if command == "uv" else ["mcp_server.py"]

    print(BANNER.format(model=f"model: {MODEL}"))
    print(f"  🦙 {LLAMA_CPP_URL}   ctx={CTX_LIMIT}\n")
    print("  Connecting MCP...", end=" ", flush=True)

    async with AsyncExitStack() as stack:
        mcp     = await stack.enter_async_context(MCPClient(command=command, args=args))
        clients = {"main": mcp}

        registry = ToolRegistry()
        await registry.build(clients)

        raw_tools = await ToolManager.get_all_tools(clients)
        print(f"  🧰 {len(raw_tools)} tools ready.\n")

        session_start = time.time()
        turn = 0

        while True:
            try:
                q = input(f"  [{turn+1}] You › ").strip()
                if not q:
                    continue
                if q.lower() in {"exit", "quit"}:
                    elapsed = int(time.time() - session_start)
                    print(f"\n  👋 Goodbye! ({turn} turns, {elapsed}s)\n")
                    break
                if q.lower() == "clear":
                    os.system("cls" if sys.platform == "win32" else "clear")
                    print(BANNER.format(model=f"model: {MODEL}"))
                    continue

                turn += 1
                t0 = time.time()
                print()

                answer, label = await run(q, raw_tools, registry)
                ms = int((time.time() - t0) * 1000)

                print_answer(answer, label)
                print(f"\n  ⏱  {ms} ms\n")

            except KeyboardInterrupt:
                print("\n  (Ctrl-C — type 'exit' to quit)\n")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())