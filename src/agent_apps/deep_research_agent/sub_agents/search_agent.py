from agents import Agent, ModelSettings, WebSearchTool

from ..config import MODEL

INSTRUCTIONS = """
You are a research assistant. Given a search term, you search the web for that term and 
produce a concise summary of the results. The summary must 2-3 paragraphs and less than 300 words.
Capture the main points and be succinct. Reply only with the summary.
"""

settings = ModelSettings(tool_choice="required")
tools = [WebSearchTool()]

search_agent = Agent(
    name="Search Agent",
    instructions=INSTRUCTIONS,
    tools=tools,
    model=MODEL,
    model_settings=settings,
)
