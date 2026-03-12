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
LLAMA_CPP_URL   = "http://127.0.0.1:8080/v1"
MODEL           = "qwen3"
MAX_TOKENS      = 1024   # generation budget (NOT context size)
CTX_LIMIT       = 4096   # must match your llama.cpp --ctx-size
CTX_SAFETY      = 0.80   # use at most 80 % of context for the prompt
MAX_PROMPT_CHARS = int(CTX_LIMIT * CTX_SAFETY * 3.5)  # ~3.5 chars per token
TOOL_RESULT_CAP = 600    # max chars stored per tool result in history
MAX_ITERATIONS  = 10

# ── Thinking-model detection ──────────────────────────────────────────────────
THINKING_MODELS = {
    "qwq", "qwen3",
    "deepseek-r1", "deepseek-r1-distill",
    "marco-o1", "sky-t1",
}

def is_thinking_model(name: str) -> bool:
    return any(tm in name.lower() for tm in THINKING_MODELS)

_env = os.getenv("SHOW_THINKING", "").strip()
SHOW_THINKING = (True  if _env == "1" else
                 False if _env == "0" else
                 is_thinking_model(MODEL))


# ── Keyword patterns ──────────────────────────────────────────────────────────
CURRENT_RE = re.compile(
    r"\b(current|now|today|tonight|live|latest|recent|right now|"
    r"this (week|month|year)|at the moment|as of|ongoing|"
    r"present(ly)?|real[-\s]?time|up[-\s]?to[-\s]?date)\b",
    re.IGNORECASE,
)
WEATHER_RE = re.compile(
    r"\b(weather|temperature|forecast|rain|snow|wind|humidity|feels like)\b",
    re.IGNORECASE,
)


# ── System prompt ─────────────────────────────────────────────────────────────
def build_system_prompt(injected_context: str = "") -> str:
    return f"""You are Aria, a concise and professional AI assistant.
{injected_context}
════════════════════════ TOOL POLICY ════════════════════════
Tools: internet_search | get_weather | get_current_time |
       read_doc_content | edit_doc_content

USE a tool ONLY when:
  • internet_search  → live news, prices, scores, post-cutoff facts
  • get_current_time → user explicitly asks for time/date
  • get_weather      → explicit weather/forecast question
  • doc tools        → reading or editing files

DO NOT use a tool when:
  ✗ You already know the answer (definitions, history, concepts, math)
  ✗ You already called that tool with the same args this turn
  ✗ The question is conversational ("hi", "thanks", etc.)

Decision rule: "Can I answer confidently from training?" → YES: answer directly.
═════════════════════════════════════════════════════════════
Reply concisely. Use markdown when helpful. Never hallucinate.
"""


# ── LLM client ────────────────────────────────────────────────────────────────
llm = OpenAI(base_url=LLAMA_CPP_URL, api_key="not-needed")


def estimate_chars(messages: list[dict]) -> int:
    """Rough character count of the serialised message list."""
    return sum(
        len(json.dumps(m.get("content") or "")) +
        len(json.dumps(m.get("tool_calls") or ""))
        for m in messages
    )


def trim_messages(messages: list[dict]) -> list[dict]:
    """
    Drop the OLDEST tool-call + tool-result pairs (keeping system + user)
    until the prompt fits within MAX_PROMPT_CHARS.
    """
    if estimate_chars(messages) <= MAX_PROMPT_CHARS:
        return messages

    # Separate fixed head (system, first user) from the rolling middle
    head  = messages[:2]   # system + first user message
    tail  = messages[2:]

    while tail and estimate_chars(head + tail) > MAX_PROMPT_CHARS:
        # Drop the first assistant tool-call block and its tool results
        # Find next assistant message with tool_calls and skip until next user/assistant without tool_calls
        dropped = False
        for i, m in enumerate(tail):
            if m.get("role") == "assistant" and m.get("tool_calls"):
                # drop this assistant block + all following tool result messages
                j = i + 1
                while j < len(tail) and tail[j].get("role") == "tool":
                    j += 1
                tail = tail[j:]
                dropped = True
                break
        if not dropped:
            break   # nothing left to drop

    trimmed = head + tail
    print(f"  ✂️  Context trimmed → {estimate_chars(trimmed):,} chars")
    return trimmed


def chat(messages: list[dict], tools=None):
    safe_messages = trim_messages(messages)
    params = {
        "model":       MODEL,
        "messages":    safe_messages,
        "temperature": 0.2,
        "max_tokens":  MAX_TOKENS,
    }
    if tools:
        params["tools"]       = tools
        params["tool_choice"] = "auto"
    return llm.chat.completions.create(**params)


# ── Parse <think> blocks ──────────────────────────────────────────────────────
_THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)

def parse_response(raw: str) -> tuple[str, str]:
    thinks  = _THINK_RE.findall(raw)
    answer  = _THINK_RE.sub("", raw).strip()
    return "\n".join(t.strip() for t in thinks), answer


def print_thinking(thinking: str):
    if not thinking:
        return
    if not SHOW_THINKING:
        print(f"  💭 [thinking: {thinking.count(chr(10))+1} lines — SHOW_THINKING=1 to show]")
        return
    w = 72
    print("\n" + "─" * w)
    print("  💭  THINKING")
    print("─" * w)
    for line in thinking.splitlines():
        print(f"  {line}")
    print("─" * w)


# ── Time context injection ────────────────────────────────────────────────────
def needs_time_context(query: str) -> bool:
    return bool(CURRENT_RE.search(query)) or bool(WEATHER_RE.search(query))


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


# ── Tool registry (built once at startup) ─────────────────────────────────────
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

    # Dedup guard
    if dedup.seen(tool_name, tool_input):
        note = f"[duplicate call to {tool_name} skipped]"
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
        output = await client.call_tool(tool_name, tool_input)
        texts  = [i.text for i in output.content if isinstance(i, TextContent)]
        full   = json.dumps(texts)

        # Cap what we store in history to avoid context overflow
        stored  = full[:TOOL_RESULT_CAP] + ("…[truncated]" if len(full) > TOOL_RESULT_CAP else "")
        preview = stored[:140].replace("\n", " ")
        print(f"  ✅ {preview}{'…' if len(stored) > 140 else ''}")
        return tool_id, stored

    except Exception as e:
        err = json.dumps({"error": str(e)})
        print(f"  ❌ {e}")
        return tool_id, err


# ── Agent loop ────────────────────────────────────────────────────────────────
async def run(query: str, tools: list, registry: ToolRegistry) -> str:

    injected = build_time_context() if needs_time_context(query) else ""
    messages: list[dict] = [
        {"role": "system", "content": build_system_prompt(injected)},
        {"role": "user",   "content": query},
    ]

    dedup = CallDedup()

    for iteration in range(1, MAX_ITERATIONS + 1):

        resp = chat(messages, tools=tools)
        msg  = resp.choices[0].message
        raw  = msg.content or ""

        thinking, clean = parse_response(raw)
        if thinking:
            print_thinking(thinking)

        if not msg.tool_calls:
            return clean

        print(f"\n  ⚙️  Round {iteration} — {len(msg.tool_calls)} call(s)")

        messages.append({
            "role":       "assistant",
            "content":    clean,    # store only the non-thinking part
            "tool_calls": [
                {
                    "id": tc.id, "type": "function",
                    "function": {"name": tc.function.name,
                                 "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ],
        })

        results = await asyncio.gather(
            *[execute_tool(tc, registry, dedup) for tc in msg.tool_calls]
        )

        for tid, result in results:
            messages.append({"role": "tool", "tool_call_id": tid, "content": result})

    # Max iterations reached — answer without tools
    print("\n⚠️  Max iterations — forcing final answer")
    messages.append({
        "role": "user",
        "content": "Based on everything above, give your final answer now. No more tool calls."
    })
    resp = chat(messages, tools=None)
    _, clean = parse_response(resp.choices[0].message.content or "")
    return clean


# ── Pretty answer box ─────────────────────────────────────────────────────────
def print_answer(text: str):
    w = 72
    print("\n" + "═" * w)
    print("AI")
    print("═" * w)
    print(text)
    print("═" * w)


# ── CLI ───────────────────────────────────────────────────────────────────────


async def main():
    command = "uv" if os.getenv("USE_UV", "0") == "1" else "python"
    args    = ["run", "mcp_server.py"] if command == "uv" else ["mcp_server.py"]

    print(BANNER.format(model=f"model: {MODEL}"))
    print(f"  🦙 {LLAMA_CPP_URL}   ctx={CTX_LIMIT}   "
          f"💭 thinking={'ON' if SHOW_THINKING else 'OFF'}\n")
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

                answer = await run(q, raw_tools, registry)
                ms     = int((time.time() - t0) * 1000)

                print_answer(answer)
                print(f"\n  ⏱  {ms} ms\n")

            except KeyboardInterrupt:
                print("\n  (Ctrl-C — type 'exit' to quit)\n")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())