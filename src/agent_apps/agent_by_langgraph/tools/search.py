from langchain_community.utilities import GoogleSerperAPIWrapper
from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, strict=True, description="The web search query.")


@tool(args_schema=SearchInput)
def search(query: str) -> str:
    """Search the web using only query. Returns up to 3 results; the limit is fixed."""
    return GoogleSerperAPIWrapper(k=3).run(query)


search.handle_validation_error = (
    'Invalid search arguments. Retry with only {"query": "your search terms"}. '
    'The result limit is fixed at 3; do not pass max_results or other parameters.'
)
