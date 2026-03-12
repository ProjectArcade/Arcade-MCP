import asyncio
import json
import os
import re
import hashlib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv

from mcp_client import MCPClient
from core.tools import ToolManager
from mcp.types import TextContent

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
LLAMA_CPP_URL    = os.getenv("LLAMA_CPP_URL",  "http://127.0.0.1:8080/v1")
MODEL            = os.getenv("LLM_MODEL",       "qwen3")
MAX_TOKENS       = int(os.getenv("MAX_TOKENS",  "1024"))
CTX_LIMIT        = 8192
CTX_SAFETY       = 0.80
MAX_PROMPT_CHARS = int(CTX_LIMIT * CTX_SAFETY * 3.5)
TOOL_RESULT_CAP  = 800
MAX_ITERATIONS   = int(os.getenv("MAX_ITER",    "10"))
WEB_HOST         = os.getenv("WEB_HOST",        "0.0.0.0")
WEB_PORT         = int(os.getenv("WEB_PORT",    "8000"))
MCP_SERVER       = os.getenv("MCP_SERVER",      "mcp_server.py")
USE_UV           = os.getenv("USE_UV",          "0") == "1"
ALLOWED_ORIGINS  = os.getenv("ALLOWED_ORIGINS", "*").split(",")

# ── Query Classifier ──────────────────────────────────────────────────────────
_LIVE_RE = re.compile(
    r"\b(weather|forecast|temperature|rain|snow|wind|humidity|"
    r"current|now|today\w*|tonight\w*|live|latest|recent|right\s+now|"
    r"this\s+(week|month|year)|as\s+of|ongoing|breaking|"
    r"price|stock|crypto|share|nse|bse|nasdaq|sensex|nifty|"
    r"score|match|game|news|trend|"
    r"search(\s+for)?|look\s+up|find\s+out|"
    r"age\s+of|how\s+old\s+is|net\s+worth|"
    r"profit|loss|closed|open|market|trading|"
    r"what time|what('s| is) the time|time (is|it)|"
    r"date today|current date|current time)\b",
    re.IGNORECASE,
)
_KNOWLEDGE_RE = re.compile(
    r"^(hi+[!?.]?|hello+[!?.]?|hey+[!?.]?|howdy|yo+|sup|"
    r"good\s?(morning|afternoon|evening|night)|"
    r"how are you|what('s| is) up|nice to meet|"
    r"thanks?[!?.]?|thank you[!?.]?|ok[!?.]?|okay[!?.]?|"
    r"sure[!?.]?|great[!?.]?|cool[!?.]?|awesome[!?.]?|"
    r"bye[!?.]?|goodbye[!?.]?|see you[!?.]?|cya[!?.]?|"
    r"what (is|are|was|were|does|do|did|means?|mean) (?!the (age|net worth)).{1,80}|"
    r"(explain|describe|define|tell me about|how does|how do|"
    r"why (is|are|does|do)|when (was|did|is)|where (is|was)|which (is|are)) .{1,80})$",
    re.IGNORECASE,
)

def needs_tools(query: str) -> bool:
    q = query.strip()
    if _LIVE_RE.search(q):
        return True
    if _KNOWLEDGE_RE.match(q) or len(q) <= 30:
        return False
    return False

# ── Time helpers ──────────────────────────────────────────────────────────────
_TIME_RE    = re.compile(r"\b(current|now|today|tonight|live|latest|recent|right\s+now|this\s+(week|month|year)|at the moment|as of|ongoing|present(ly)?|what time|what('s| is) the time|time (is|it is)|date (is|today))\b", re.IGNORECASE)
_WEATHER_RE = re.compile(r"\b(weather|forecast|rain|snow|wind|humidity|feels like|temperature)\b", re.IGNORECASE)

def needs_time_ctx(q: str) -> bool:
    return bool(_TIME_RE.search(q)) or bool(_WEATHER_RE.search(q))

def time_context() -> str:
    now_utc = datetime.now(timezone.utc)
    tz_name = os.getenv("LOCAL_TZ", "UTC")
    try:    now_local = now_utc.astimezone(ZoneInfo(tz_name))
    except: now_local, tz_name = now_utc, "UTC"
    return (f"\n⏰ NOW: {now_utc.strftime('%A %d %B %Y %H:%M UTC')} | "
            f"Local ({tz_name}): {now_local.strftime('%H:%M')}\n")

# ── LLM ───────────────────────────────────────────────────────────────────────
llm = OpenAI(base_url=LLAMA_CPP_URL, api_key="not-needed")

_SYSTEM_CHAT = (
    "You are Aria, a concise professional AI assistant. Developed by Abhinav Thakur you are a part of Project Arcade. "
    "Answer clearly. Use markdown when it adds value. Never make up facts."
)

def system_tools(injected: str = "", tool_hint: Optional[str] = None) -> str:
    hint_line = ""
    if tool_hint:
        hint_line = (
            f"\nIMPORTANT: The user explicitly invoked the '{tool_hint}' tool via a slash command. "
            f"You MUST call '{tool_hint}' as your first tool call. "
            f"Do NOT call any other tool before '{tool_hint}'.\n"
        )
    return (
        f"You are Aria, a concise professional AI assistant. Developed by Abhinav Thakur you are a part of Project Arcade.\n"
        f"{injected}{hint_line}\n"
        "Use tools ONLY for live/current data (weather, news, prices, time, web search). "
        "Never call a tool for general knowledge. "
        "Never repeat a tool call with identical arguments. "
        "Answer concisely using markdown when helpful."
    )

def estimate_chars(msgs):
    return sum(
        len(json.dumps(m.get("content") or "")) + len(json.dumps(m.get("tool_calls") or ""))
        for m in msgs
    )

def trim_messages(messages):
    if estimate_chars(messages) <= MAX_PROMPT_CHARS:
        return messages
    # Always keep system prompt (index 0)
    head, tail = messages[:1], messages[1:]
    while tail and estimate_chars(head + tail) > MAX_PROMPT_CHARS:
        dropped = False
        for i, m in enumerate(tail):
            if m.get("role") == "assistant" and m.get("tool_calls"):
                j = i + 1
                while j < len(tail) and tail[j].get("role") == "tool":
                    j += 1
                tail = tail[j:]; dropped = True; break
        if not dropped:
            # Drop oldest non-system message
            tail = tail[1:]
            break
    return head + tail

def llm_chat(messages, tools=None, stream=False):
    params = {
        "model": MODEL,
        "messages": trim_messages(messages),
        "temperature": 0.2,
        "max_tokens": MAX_TOKENS,
        "stream": stream,
    }
    if tools:
        params["tools"] = tools
        params["tool_choice"] = "auto"
    return llm.chat.completions.create(**params)

# ── Tool registry ─────────────────────────────────────────────────────────────
class ToolRegistry:
    def __init__(self): self._map = {}
    async def build(self, clients):
        for c in clients.values():
            for t in await c.list_tools():
                self._map[t.name] = c
    def client_for(self, name): return self._map.get(name)
    def tool_names(self): return list(self._map.keys())

class CallDedup:
    def __init__(self): self._seen = set()
    def _key(self, n, a): return f"{n}::{hashlib.md5(json.dumps(a, sort_keys=True).encode()).hexdigest()}"
    def seen(self, n, a): return self._key(n, a) in self._seen
    def mark(self, n, a): self._seen.add(self._key(n, a))

# ── App state ─────────────────────────────────────────────────────────────────
app_state = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    command = "uv" if USE_UV else "python"
    args    = ["run", MCP_SERVER] if USE_UV else [MCP_SERVER]
    from contextlib import AsyncExitStack
    stack = AsyncExitStack()
    await stack.__aenter__()
    mcp = await stack.enter_async_context(MCPClient(command=command, args=args))
    clients = {"main": mcp}
    registry = ToolRegistry()
    await registry.build(clients)
    raw_tools = await ToolManager.get_all_tools(clients)
    app_state["clients"]   = clients
    app_state["registry"]  = registry
    app_state["raw_tools"] = raw_tools
    app_state["stack"]     = stack
    print(f"✅ MCP ready — {len(raw_tools)} tools: {registry.tool_names()}")
    yield
    await stack.__aexit__(None, None, None)

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── SSE helpers ───────────────────────────────────────────────────────────────
def sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"

def sse_debug(text: str)  -> str: return sse({"type": "debug",       "text": text})
def sse_tool(name, args)  -> str: return sse({"type": "tool_call",   "name": name, "args": args})
def sse_result(name, res) -> str: return sse({"type": "tool_result", "name": name, "result": res[:120]})
def sse_answer(text: str) -> str: return sse({"type": "answer",      "text": text})
def sse_error(text: str)  -> str: return sse({"type": "error",       "text": text})

# ── Execute tool ──────────────────────────────────────────────────────────────
async def execute_tool_sse(tc, registry: ToolRegistry, dedup: CallDedup):
    tool_name = tc.function.name
    tool_id   = tc.id
    try:    tool_input = json.loads(tc.function.arguments)
    except: tool_input = {}

    if dedup.seen(tool_name, tool_input):
        note = f"[duplicate {tool_name} skipped]"
        return tool_id, json.dumps({"note": note}), sse_debug(note)

    dedup.mark(tool_name, tool_input)
    event = sse_tool(tool_name, tool_input)

    client = registry.client_for(tool_name)
    if client is None:
        err = json.dumps({"error": f"tool '{tool_name}' not found"})
        return tool_id, err, event + sse_error(f"Tool not found: {tool_name}")

    try:
        output = await client.call_tool(tool_name, tool_input)
        texts  = [i.text for i in output.content if isinstance(i, TextContent)]
        full   = json.dumps(texts)
        stored = full[:TOOL_RESULT_CAP] + ("…[truncated]" if len(full) > TOOL_RESULT_CAP else "")
        return tool_id, stored, event + sse_result(tool_name, stored)
    except Exception as e:
        err = json.dumps({"error": str(e)})
        return tool_id, err, event + sse_error(str(e))

# ── Request models ────────────────────────────────────────────────────────────
class HistoryMessage(BaseModel):
    role:    str   # "user" | "assistant"
    content: str

class ChatRequest(BaseModel):
    query:       str
    force_tools: bool                  = False
    tool_hint:   Optional[str]         = None   # e.g. "internet_search"
    history:     List[HistoryMessage]  = []

# ── Agent stream ──────────────────────────────────────────────────────────────
async def agent_stream(
    query:       str,
    force_tools: bool                 = False,
    tool_hint:   Optional[str]        = None,
    history:     List[HistoryMessage] = [],
):
    registry  = app_state["registry"]
    raw_tools = app_state["raw_tools"]

    use_tools = force_tools or needs_tools(query)

    # Build history prefix — keep last 20 messages (10 pairs)
    hist_msgs = [
        {"role": m.role, "content": m.content}
        for m in history[-20:]
    ]

    # ── Direct answer (no tools) — streamed token by token ──────────────────
    if not use_tools:
        yield sse_debug("conversation — answering directly")
        messages = (
            [{"role": "system", "content": _SYSTEM_CHAT}]
            + hist_msgs
            + [{"role": "user", "content": query}]
        )
        stream = await asyncio.to_thread(llm_chat, messages, None, True)
        answer = ""
        for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            if delta:
                answer += delta
                yield sse({"type": "token", "text": delta})
        yield sse_answer(answer)
        yield "data: [DONE]\n\n"
        return

    # ── Tool path ─────────────────────────────────────────────────────────────
    injected = time_context() if needs_time_ctx(query) else ""
    messages = (
        [{"role": "system", "content": system_tools(injected, tool_hint)}]
        + hist_msgs
        + [{"role": "user", "content": query}]
    )
    dedup = CallDedup()

    for iteration in range(1, MAX_ITERATIONS + 1):
        yield sse_debug(f"LLM call #{iteration}")

        # ── Stream this LLM call so tokens appear immediately ────────────────
        stream = await asyncio.to_thread(llm_chat, messages, raw_tools, True)

        # Accumulate streamed chunks; collect tool_calls in parallel
        raw            = ""
        tool_calls_acc = {}   # index -> {id, name, arguments}

        for chunk in stream:
            choice = chunk.choices[0]
            delta  = choice.delta

            # Accumulate text content
            if delta.content:
                raw += delta.content
                yield sse({"type": "token", "text": delta.content})

            # Accumulate tool call deltas
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {
                            "id":        tc_delta.id or "",
                            "name":      tc_delta.function.name or "" if tc_delta.function else "",
                            "arguments": "",
                        }
                    if tc_delta.id:
                        tool_calls_acc[idx]["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            tool_calls_acc[idx]["name"] += tc_delta.function.name
                        if tc_delta.function.arguments:
                            tool_calls_acc[idx]["arguments"] += tc_delta.function.arguments

        # No tool calls → final answer already streamed token-by-token
        if not tool_calls_acc:
            yield sse_answer(raw)
            yield "data: [DONE]\n\n"
            return

        yield sse_debug(f"Round {iteration} — {len(tool_calls_acc)} tool call(s)")

        # Build fake tool_call objects compatible with execute_tool_sse
        class _Fn:
            def __init__(self, name, arguments): self.name = name; self.arguments = arguments
        class _TC:
            def __init__(self, id, fn): self.id = id; self.function = fn

        tc_list = [
            _TC(v["id"], _Fn(v["name"], v["arguments"]))
            for v in tool_calls_acc.values()
        ]

        messages.append({
            "role": "assistant",
            "content": raw,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tc_list
            ],
        })

        results = await asyncio.gather(
            *[execute_tool_sse(tc, registry, dedup) for tc in tc_list]
        )

        for tid, result, events in results:
            for line in events.split("\n\n"):
                if line.strip():
                    yield line + "\n\n"
            messages.append({"role": "tool", "tool_call_id": tid, "content": result})

    # Fallback after max iterations
    yield sse_debug("Max iterations — forcing answer")
    messages.append({"role": "user", "content": "Give your final answer now. No more tool calls."})
    stream = await asyncio.to_thread(llm_chat, messages, None, True)
    answer = ""
    for chunk in stream:
        delta = chunk.choices[0].delta.content or ""
        if delta:
            answer += delta
            yield sse({"type": "token", "text": delta})
    yield sse_answer(answer)
    yield "data: [DONE]\n\n"

# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    registry = app_state.get("registry")
    return {
        "status": "ok",
        "model":  MODEL,
        "tools":  registry.tool_names() if registry else [],
    }

@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    return StreamingResponse(
        agent_stream(
            req.query.strip(),
            req.force_tools,
            req.tool_hint,
            req.history,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

# ── Static files ──────────────────────────────────────────────────────────────
_HERE   = os.path.dirname(os.path.abspath(__file__))
_STATIC = os.path.join(_HERE, "web")
if not os.path.isdir(_STATIC):
    _STATIC = _HERE
app.mount("/", StaticFiles(directory=_STATIC, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host=WEB_HOST, port=WEB_PORT, reload=False)