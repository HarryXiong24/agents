from langchain.agents.middleware import wrap_tool_call


@wrap_tool_call
def log_tool_calls(request, handler):
    """Log each tool execution; register with middleware=[log_tool_calls].

    request.tool_call contains the tool name, arguments, and call ID.
    handler(request) runs the next wrapper or the tool itself. Return its
    result unchanged so the agent receives the ToolMessage or Command.
    """
    call = request.tool_call
    print(f"  [middleware] calling {call['name']} with {call['args']}")
    return handler(request)
