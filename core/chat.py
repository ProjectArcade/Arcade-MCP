from core.claude import Claude
from mcp_client import MCPClient
from core.tools import ToolManager


class Chat:
    def __init__(self, claude_service: Claude, clients: dict[str, MCPClient]):
        self.claude_service: Claude = claude_service
        self.clients: dict[str, MCPClient] = clients
        self.messages: list = []

    async def _process_query(self, query: str):
        self.messages.append({"role": "user", "content": query})

    async def run(self, query: str) -> str:
        final_text_response = ""
        await self._process_query(query)

        while True:
            response = self.claude_service.chat(
                messages=self.messages,
                tools=await ToolManager.get_all_tools(self.clients),
            )

            stop_reason = self.claude_service.stop_reason(response)
            self.claude_service.add_assistant_message(self.messages, response)

            if stop_reason == "tool_use":
                tool_calls = response.choices[0].message.tool_calls or []
                print(f"\n🤖 Groq wants to call {len(tool_calls)} tool(s):")
                tool_result_parts = await ToolManager.execute_tool_requests(
                    self.clients, response
                )
                for tool_result in tool_result_parts:
                    self.messages.append(tool_result)
            else:
                final_text_response = self.claude_service.text_from_message(response)
                break

        return final_text_response


