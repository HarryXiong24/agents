from langchain_community.tools import GoogleSerperRun
from langchain_community.utilities import GoogleSerperAPIWrapper
from langchain_core.tools import tool


@tool
def search(query: str) -> str:
    """Search online for information matching the query and return the results."""
    search_tool = GoogleSerperRun(api_wrapper=GoogleSerperAPIWrapper())
    return search_tool.invoke(query)
