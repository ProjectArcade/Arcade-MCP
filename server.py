import asyncio
import json
import sys
import os
import uuid

from openai import OpenAI
from contextlib import AsyncExitStack

from mcp_client import MCPClient
from core.tools import ToolManager
from mcp.types import TextContent


# ── Config ──────────────────────────────────────────────
LLAMA_CPP_URL  = "http://127.0.0.1:8080/v1"
MODEL          = "qwen3"
MAX_TOKENS     = 4096
MAX_ITERATIONS = 6

SYSTEM_PROMPT = """
You are a smart autonomous AI assistant.

Tool usage policy:
- You have access to tools: internet_search, get_weather, get_current_time,
  read_doc_content, edit_doc_content.
- Use tools ONLY when necessary.
- Do NOT use internet_search for basic knowledge.
- Use internet_search when user asks about latest information,
  current events, prices, live data, unknown facts.
- Use get_weather only for weather queries.
- Use get_current_time only for time/date queries.
- Use document tools only for file operations.

Reason step-by-step.
You may call multiple tools.
Stop when confident and give final answer.
"""


# ── LLM Client ──────────────────────────────────────────
llm = OpenAI(
    base_url=LLAMA_CPP_URL,
    api_key="not-needed",
)


def chat(messages, tools=None):
    params = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": MAX_TOKENS,
    }
    if tools:
        params["tools"] = tools
        params["tool_choice"] = "auto"

    return llm.chat.completions.create(**params)


def text_from(response):
    return response.choices[0].message.content or ""


# ── Execute Tool ─────────────────────────────────────────
async def execute_tool(tc, mcp_clients: dict):

    tool_name = tc.function.name
    raw_args  = tc.function.arguments
    tool_id   = tc.id

    try:
        tool_input = json.loads(raw_args)
    except:
        tool_input = {}

    print(f"🔧 Calling Tool → {tool_name} {tool_input}")

    for c in mcp_clients.values():
        tools = await c.list_tools()

        if any(t.name == tool_name for t in tools):
            try:
                output = await c.call_tool(tool_name, tool_input)

                texts = [
                    i.text for i in output.content
                    if isinstance(i, TextContent)
                ]

                result = json.dumps(texts)
                print(f"✅ Tool Result → {result[:120]}")
                return tool_id, result

            except Exception as e:
                err = json.dumps({"error": str(e)})
                print("❌ Tool Error:", e)
                return tool_id, err

    return tool_id, json.dumps({"error": "tool not found"})


# ── Dynamic Agent Loop ───────────────────────────────────
async def run(query: str, mcp_clients: dict):

    tools = await ToolManager.get_all_tools(mcp_clients)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": query},
    ]

    iteration = 0

    while True:
        iteration += 1

        if iteration > MAX_ITERATIONS:
            print("⚠️ Max iterations reached → forcing final answer")
            final = chat(messages, tools=None)
            return text_from(final)

        response = chat(messages, tools=tools)

        msg = response.choices[0].message

        # Normal answer → done
        if not msg.tool_calls:
            return msg.content

        # Append assistant tool call
        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        })

        # Execute tools
        for tc in msg.tool_calls:
            tool_id, result = await execute_tool(tc, mcp_clients)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_id,
                "content": result,
            })


# ── CLI ──────────────────────────────────────────────────
async def main():

    command = "uv" if os.getenv("USE_UV", "0") == "1" else "python"
    args    = ["run", "mcp_server.py"] if command == "uv" else ["mcp_server.py"]

    print("🚀 Connecting MCP...")
    print(f"🦙 Using llama.cpp → {LLAMA_CPP_URL}")

    async with AsyncExitStack() as stack:

        mcp = await stack.enter_async_context(
            MCPClient(command=command, args=args)
        )

        clients = {"main": mcp}

        tools = await ToolManager.get_all_tools(clients)

        print(f"🧰 Loaded {len(tools)} tools")
        print("Type message (exit to quit)\n")

        while True:
            try:
                q = input("> ").strip()

                if q.lower() in ["exit", "quit"]:
                    break

                ans = await run(q, clients)
                print("\n", ans, "\n")

            except KeyboardInterrupt:
                break


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(
            asyncio.WindowsProactorEventLoopPolicy()
        )

    asyncio.run(main())