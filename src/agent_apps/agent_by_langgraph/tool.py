from langchain_core.tools import tool


@tool
def get_share_price(symbol: str) -> float:
    """Return the current share price for a given ticker symbol."""
    fake_prices = {"AAPL": 241.5, "GOOG": 168.2, "AMZN": 198.0}
    return fake_prices.get(symbol.upper(), 0.0)


# @tool converts the Python function into a LangChain StructuredTool object.
# The object exposes tool metadata and keeps the original function in .func.
if __name__ == "__main__":
    print("name:", get_share_price.name)
    print("description:", get_share_price.description)
    print("args:", get_share_price.args)

    # .invoke() uses LangChain's tool interface: it validates the input against
    # the argument schema and supports callbacks and tracing before executing
    # the underlying function. Calling .invoke() does not itself call an LLM.
    print("via tool interface:", get_share_price.invoke({"symbol": "AAPL"}))

    # .func() calls the original Python function directly, bypassing LangChain's
    # input validation, callbacks, and tracing for this tool invocation.
    print("via original function:", get_share_price.func("AAPL"))

    # Calling get_share_price("AAPL") would raise TypeError because the decorated
    # object is a StructuredTool, not a callable Python function.
    # Without @tool, get_share_price("AAPL") would be a normal function call.
