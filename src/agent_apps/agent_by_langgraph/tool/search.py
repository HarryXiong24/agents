from langchain_community.tools import GoogleSerperRun
from langchain_community.utilities import GoogleSerperAPIWrapper
from langchain_core.tools import tool


@tool
def search():
    """Search for information online."""
    search = GoogleSerperRun(api_wrapper=GoogleSerperAPIWrapper())
    return search
