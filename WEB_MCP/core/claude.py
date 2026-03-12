from groq import Groq

class Claude:
    def __init__(self, model: str):
        self.client = Groq()
        self.model = model

    def add_user_message(self, messages: list, message):
        if isinstance(message, str):
            messages.append({"role": "user", "content": message})
        elif isinstance(message, list):
            messages.append({"role": "user", "content": message})
        else:
            messages.append({"role": "user", "content": str(message)})

    def add_assistant_message(self, messages: list, message):
        # Groq response → convert to dict for message history
        msg = message.choices[0].message
        assistant_msg = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                }
                for tc in msg.tool_calls
            ]
        messages.append(assistant_msg)

    def text_from_message(self, message):
        return message.choices[0].message.content or ""

    def stop_reason(self, message):
        # Normalize Groq finish_reason to match Anthropic style
        reason = message.choices[0].finish_reason
        if reason == "tool_calls":
            return "tool_use"
        return reason

    def get_tool_calls(self, message):
        # Returns tool calls from Groq response
        return message.choices[0].message.tool_calls or []

    def chat(
        self,
        messages,
        system=None,
        temperature=1.0,
        stop_sequences=[],
        tools=None,
        thinking=False,
        thinking_budget=1024,
    ):
        all_messages = []

        if system:
            all_messages.append({"role": "system", "content": system})

        all_messages.extend(messages)

        params = {
            "model": self.model,
            "max_tokens": 8000,
            "messages": all_messages,
            "temperature": temperature,
        }

        if tools:
            params["tools"] = tools
            params["tool_choice"] = "auto"

        return self.client.chat.completions.create(**params)