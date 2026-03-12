import asyncio
import json
import os
import re
import time
import hashlib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from contextlib import asynccontextmanager

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
    "You are Aria, a concise professional AI assistant. "
    "Answer clearly. Use markdown when it adds value. Never make up facts."
)

def system_tools(injected: str = "") -> str:
    return (
        f"You are Aria, a concise professional AI assistant.\n{injected}\n"
        "Use tools ONLY for live/current data (weather, news, prices, time). "
        "Never call a tool for general knowledge. "
        "Never repeat a tool call with identical arguments. "
        "Answer concisely using markdown when helpful."
    )

def estimate_chars(msgs):
    return sum(len(json.dumps(m.get("content") or "")) + len(json.dumps(m.get("tool_calls") or "")) for m in msgs)

def trim_messages(messages):
    if estimate_chars(messages) <= MAX_PROMPT_CHARS:
        return messages
    head, tail = messages[:2], messages[2:]
    while tail and estimate_chars(head + tail) > MAX_PROMPT_CHARS:
        dropped = False
        for i, m in enumerate(tail):
            if m.get("role") == "assistant" and m.get("tool_calls"):
                j = i + 1
                while j < len(tail) and tail[j].get("role") == "tool":
                    j += 1
                tail = tail[j:]; dropped = True; break
        if not dropped: break
    return head + tail

def llm_chat(messages, tools=None):
    params = {"model": MODEL, "messages": trim_messages(messages),
              "temperature": 0.2, "max_tokens": MAX_TOKENS}
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
    def _key(self, n, a): return f"{n}::{hashlib.md5(json.dumps(a,sort_keys=True).encode()).hexdigest()}"
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
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS,
                   allow_methods=["*"], allow_headers=["*"])

# ── SSE helpers ───────────────────────────────────────────────────────────────
def sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"

def sse_debug(text: str)  -> str: return sse({"type": "debug",       "text": text})
def sse_tool(name, args)  -> str: return sse({"type": "tool_call",   "name": name, "args": args})
def sse_result(name, res) -> str: return sse({"type": "tool_result", "name": name, "result": res[:120]})
def sse_answer(text: str) -> str: return sse({"type": "answer",      "text": text})
def sse_error(text: str)  -> str: return sse({"type": "error",       "text": text})

# ── Execute tool (yields SSE lines) ──────────────────────────────────────────
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
        result_event = sse_result(tool_name, stored)
        return tool_id, stored, event + result_event
    except Exception as e:
        err = json.dumps({"error": str(e)})
        return tool_id, err, event + sse_error(str(e))

# ── Agent stream generator ────────────────────────────────────────────────────
async def agent_stream(query: str):
    registry  = app_state["registry"]
    raw_tools = app_state["raw_tools"]

    use_tools = needs_tools(query)

    if not use_tools:
        yield sse_debug("conversation — answering directly")
        messages = [
            {"role": "system", "content": _SYSTEM_CHAT},
            {"role": "user",   "content": query},
        ]
        resp   = await asyncio.to_thread(llm_chat, messages)
        answer = resp.choices[0].message.content or ""
        yield sse_answer(answer)
        yield "data: [DONE]\n\n"
        return

    # Tools path
    injected = time_context() if needs_time_ctx(query) else ""
    messages = [
        {"role": "system", "content": system_tools(injected)},
        {"role": "user",   "content": query},
    ]
    dedup = CallDedup()

    for iteration in range(1, MAX_ITERATIONS + 1):
        yield sse_debug(f"LLM call #{iteration}")
        resp = await asyncio.to_thread(llm_chat, messages, raw_tools)
        msg  = resp.choices[0].message
        raw  = msg.content or ""

        if not msg.tool_calls:
            yield sse_answer(raw)
            yield "data: [DONE]\n\n"
            return

        yield sse_debug(f"Round {iteration} — {len(msg.tool_calls)} tool call(s)")

        messages.append({
            "role": "assistant", "content": raw,
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ],
        })

        results = await asyncio.gather(
            *[execute_tool_sse(tc, registry, dedup) for tc in msg.tool_calls]
        )

        for tid, result, events in results:
            for line in events.split("\n\n"):
                if line.strip():
                    yield line + "\n\n"
            messages.append({"role": "tool", "tool_call_id": tid, "content": result})

    # Fallback
    yield sse_debug("Max iterations — forcing answer")
    messages.append({"role": "user", "content": "Give your final answer now. No more tool calls."})
    resp   = await asyncio.to_thread(llm_chat, messages)
    answer = resp.choices[0].message.content or ""
    yield sse_answer(answer)
    yield "data: [DONE]\n\n"

# ── Routes ────────────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    query: str

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
        agent_stream(req.query.strip()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

# ── Serve static files (HTML/CSS/JS) ─────────────────────────────────────────
# Resolve static dir relative to server.py so cwd doesn't matter
_HERE = os.path.dirname(os.path.abspath(__file__))
_STATIC = os.path.join(_HERE, "web")
if not os.path.isdir(_STATIC):
    _STATIC = _HERE   # fallback: HTML/CSS/JS alongside server.py
app.mount("/", StaticFiles(directory=_STATIC, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host=WEB_HOST, port=WEB_PORT, reload=False)