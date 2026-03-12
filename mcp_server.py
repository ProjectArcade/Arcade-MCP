from pydantic import Field
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.prompts import base
import httpx
from datetime import datetime
import pytz
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

mcp = FastMCP("DocumentMCP", log_level="ERROR")

docs = {
    "deposition.md": "This deposition covers the testimony of Angela Smith, P.E.",
    "report.pdf": "The report details the state of a 20m condenser tower.",
    "financials.docx": "These financials outline the project's budget and expenditures.",
    "outlook.pdf": "This document presents the projected future performance of the system.",
    "plan.md": "The plan outlines the steps for the project's implementation.",
    "spec.txt": "These specifications define the technical requirements for the equipment.",
}

@mcp.tool(
    name="read_doc_content",
    description="Read the content of a document and return it as a string."
)
def read_document(
    doc_id: str = Field(description="ID of the document to read.")
):
    if doc_id not in docs:
        raise ValueError(f"Document with ID '{doc_id}' not found.")
    return docs[doc_id]


@mcp.tool(
    name="edit_doc_content",
    description="Edit a document by replacing the content with a new string."
)
def edit_document(
    doc_id: str = Field(description="ID of the document that will be edited."),
    old_str: str = Field(description="The text to replace, must match exactly with whitespace."),
    new_str: str = Field(description="The new text to replace the old text with.")
):
    if doc_id not in docs:
        raise ValueError(f"Document with ID '{doc_id}' not found.")
    docs[doc_id] = docs[doc_id].replace(old_str, new_str)
    return f"Document '{doc_id}' updated successfully."


@mcp.tool(
    name="get_weather",
    description="Get the current weather for a given city or location."
)
def get_weather(
    location: str = Field(description="City name or location to get weather for. e.g. 'Mumbai', 'New York'")
):
    url = f"https://wttr.in/{location}?format=j1"

    with httpx.Client() as client:
        response = client.get(url, timeout=10)

    if response.status_code != 200:
        raise ValueError(f"Could not fetch weather for '{location}'.")

    data = response.json()
    current = data["current_condition"][0]
    area = data["nearest_area"][0]

    city = area["areaName"][0]["value"]
    country = area["country"][0]["value"]
    temp_c = current["temp_C"]
    temp_f = current["temp_F"]
    feels_like = current["FeelsLikeC"]
    humidity = current["humidity"]
    description = current["weatherDesc"][0]["value"]
    wind_kmph = current["windspeedKmph"]

    return (
        f"Weather in {city}, {country}:\n"
        f"  condition  : {description}\n"
        f"  temperature: {temp_c}°C / {temp_f}°F\n"
        f"  feels like : {feels_like}°C\n"
        f"  humidity   : {humidity}%\n"
        f"  wind speed : {wind_kmph} km/h"
    )


@mcp.tool(
    name="get_current_time",
    description="Get the current date and time. Optionally provide a timezone like 'Asia/Kolkata', 'America/New_York', 'Europe/London'. If no timezone given defaults to UTC."
)
def get_current_time(
    timezone: str = Field(
        default="UTC",
        description="Timezone name e.g. 'Asia/Kolkata', 'America/New_York', 'Europe/London', 'UTC'."
    )
):
    try:
        tz = pytz.timezone(timezone)
        now = datetime.now(tz)
        return (
            f"Current time in {timezone}:\n"
            f"  date : {now.strftime('%A, %d %B %Y')}\n"
            f"  time : {now.strftime('%I:%M:%S %p')}\n"
            f"  24hr : {now.strftime('%H:%M:%S')}\n"
            f"  UTC offset: {now.strftime('%z')}"
        )
    except pytz.UnknownTimeZoneError:
        raise ValueError(f"Unknown timezone '{timezone}'. Use format like 'Asia/Kolkata' or 'America/New_York'.")


@mcp.tool(
    name="internet_search",
    description="Search the internet using Tavily. Use this to find current information, news, or answer questions that require web search. Returns top search results with titles, content snippets, and URLs."
)
def internet_search(
    query: str = Field(description="Search query to look up on the internet. Be specific and clear."),
    count: int = Field(default=5, description="Number of results to return (1-10, default 5)"),
    search_depth: str = Field(
        default="basic",
        description="Search depth: 'basic' for faster results, 'advanced' for more thorough search."
    )
):
    """
    Search the web using Tavily Search API.
    Requires TAVILY_API_KEY in .env file.
    Get a free API key at: https://tavily.com
    """
    api_key = os.getenv("TAVILY_API_KEY")

    if not api_key or api_key == "Your_Tavily_API_Key_Here":
        raise ValueError(
            "❌ TAVILY_API_KEY not configured!\n"
            "1. Get a free API key at: https://tavily.com\n"
            "2. Create a .env file in the project root\n"
            "3. Add: TAVILY_API_KEY=your_actual_key\n"
            "4. Restart the server"
        )

    # Clamp count between 1 and 10
    count = max(1, min(count, 10))

    # Validate search_depth
    if search_depth not in ("basic", "advanced"):
        search_depth = "basic"

    url = "https://api.tavily.com/search"
    headers = {
        "Content-Type": "application/json",
    }
    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": count,
        "search_depth": search_depth,
        "include_answer": True,       # Tavily can return a direct AI answer
        "include_raw_content": False,
    }

    try:
        with httpx.Client() as client:
            response = client.post(url, headers=headers, json=payload, timeout=20)

        if response.status_code == 401:
            raise ValueError(
                "❌ Invalid TAVILY_API_KEY\n"
                "Check your API key in the .env file and restart the server."
            )
        elif response.status_code == 429:
            raise ValueError(
                "⚠️ Tavily Search rate limit exceeded.\n"
                "Check your usage at https://tavily.com"
            )
        elif response.status_code != 200:
            raise ValueError(f"Tavily Search API error: HTTP {response.status_code} — {response.text}")

        data = response.json()

        output_lines = [f"🔍 Search Results for '{query}':\n"]

        # Include the AI-generated answer if available
        answer = data.get("answer")
        if answer:
            output_lines.append(f"💡 Quick Answer: {answer}\n")

        results = data.get("results", [])
        if not results:
            return f"No results found for: '{query}'"

        for i, result in enumerate(results, 1):
            title = result.get("title", "No title")
            content = result.get("content", "No description")
            result_url = result.get("url", "")
            score = result.get("score")

            output_lines.append(f"{i}. **{title}**")
            output_lines.append(f"   {content}")
            if score is not None:
                output_lines.append(f"   relevance: {score:.2f}")
            output_lines.append(f"   🔗 {result_url}\n")

        return "\n".join(output_lines).strip()

    except httpx.RequestError as e:
        raise ValueError(f"Network error while contacting Tavily: {str(e)}")


@mcp.resource(
    "docs://documents",
    mime_type="application/json"
)
def list_docs() -> list[str]:
    return list(docs.keys())


@mcp.resource(
    "docs://documents/{doc_id}",
    mime_type="text/plain"
)
def fetch_doc(doc_id: str) -> str:
    if doc_id not in docs:
        raise ValueError(f"Document with ID '{doc_id}' not found.")
    return docs[doc_id]


@mcp.prompt(
    name="format",
    description="Rewrite the content of the document in Markdown format"
)
def format_document(
    doc_id: str = Field(description="ID of the document to format.")
) -> list[base.Message]:
    prompt = f"""
Your goal is to reformat a document to be written with markdown syntax.

The id of the document you need to reformat is:
<document_id>
{doc_id}
</document_id>

Follow these steps IN ORDER:

Step 1: Use the 'read_doc_content' tool to read the EXACT current content of the document.

Step 2: Rewrite that content in markdown format with headers, bullet points, tables etc.

Step 3: Use the 'edit_doc_content' tool to save it:
   - old_str: must be the EXACT text returned from Step 1 (copy it exactly)
   - new_str: your reformatted markdown version

Step 4: Confirm to the user the document has been reformatted and show them the new content.

IMPORTANT: old_str must be copied EXACTLY from the read result — do not guess or make it up!
"""
    return [base.UserMessage(prompt)]


@mcp.prompt(
    name="summarize",
    description="Summarize the content of a document in a few sentences"
)
def summarize_document(
    doc_id: str = Field(description="ID of the document to summarize.")
) -> list[base.Message]:
    prompt = f"""
Your goal is to summarize a document in a few clear sentences.

The id of the document you need to summarize is:
<document_id>
{doc_id}
</document_id>

Follow these steps IN ORDER:

Step 1: Use the 'read_doc_content' tool to read the content of the document.

Step 2: Write a concise summary covering:
   - What the document is about
   - Key points or findings
   - Any important details

Step 3: Present the summary clearly to the user.
"""
    return [base.UserMessage(prompt)]


if __name__ == "__main__":
    mcp.run(transport="stdio")