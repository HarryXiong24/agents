# Middleware hooks

These synchronous examples are enabled in `agent.py` and `llm.py` through the `middleware`
argument to `create_agent`. They log execution without changing state or results.

| Example | Hook | When it runs |
| --- | --- | --- |
| `log_agent_start.py` | `before_agent` | Once at the start of each invocation |
| `log_model_request.py` | `before_model` | Before every model call |
| `time_model_calls.py` | `wrap_model_call` | Around each model call; records duration even on failure |
| `log_tool_calls.py` | `wrap_tool_call` | Around each tool call |
| `log_model_response.py` | `after_model` | After each model response; logs tool-call count and available token usage |
| `log_agent_end.py` | `after_agent` | Once after successful completion |

A tool-using turn can repeat the model hooks several times. Agent hooks run once
per `invoke`, rather than once for the entire checkpointed conversation.
These wrap hooks return the handler's result. Before/after hooks can return
state updates; these logging examples return `None` to leave state unchanged.

In the installed LangChain version, a completed `ToolStrategy` structured response
can route directly to `after_agent`, skipping `after_model` for that final call.
The structured-output tool is handled internally rather than by `wrap_tool_call`.
The timing wrapper still runs around that model call.

These examples target `invoke`. For `ainvoke`, supply asynchronous hook
implementations as described in the documentation.

## Use both wrappers

Run this example with the project's Python environment and a Groq API key in `.env`
(`GROQ_API_KEY`).
The weather tool returns demo data. The same registration works with a model
instance, such as the `ChatGroq` instance in `llm.py`.

```python
from langchain.agents import create_agent
from agent_apps.agent_by_langgraph.utils.chat_model import create_model

from agent_apps.agent_by_langgraph.middlewares.log_tool_calls import log_tool_calls
from agent_apps.agent_by_langgraph.middlewares.time_model_calls import time_model_calls
from agent_apps.agent_by_langgraph.tools.get_weather import get_weather

agent = create_agent(
    model=create_model(),
    tools=[get_weather],
    system_prompt="Use get_weather to answer weather questions.",
    middleware=[time_model_calls, log_tool_calls],
)

result = agent.invoke(
    {"messages": [{"role": "user", "content": "What is the weather in London?"}]}
)
print(result["messages"][-1].content)
```

Pass the decorated objects directly: `log_tool_calls`, not `log_tool_calls()`.
Direct calls to `model.invoke()` or `get_weather.invoke()` do not run this
agent's middleware.

## `wrap_tool_call`: surround a tool execution

The existing `log_tool_calls.py` demonstrates logging tool names and arguments.
To log completion as well, the wrapper can follow this pattern:

```python
from langchain.agents.middleware import wrap_tool_call


@wrap_tool_call
def trace_tool(request, handler):
    name = request.tool_call["name"]
    print(f"Starting tool: {name}")
    result = handler(request)
    print(f"Finished tool: {name}")
    return result
```

Register this variant with `middleware=[trace_tool]`. `handler(request)` executes
the next tool wrapper or the actual tool. The result can be a `ToolMessage` or a
`Command`; returning it unchanged preserves the tool's output and state updates.
If execution raises, the completion message is skipped and the error propagates.

## `wrap_model_call`: surround a model request

The existing `time_model_calls.py` measures duration with a `finally` block,
so it records time on both success and failure. A wrapper can also adjust a
single request's settings:

```python
from langchain.agents.middleware import wrap_model_call


@wrap_model_call
def use_low_temperature(request, handler):
    updated_request = request.override(
        model_settings={**request.model_settings, "temperature": 0.1}
    )
    return handler(updated_request)
```

Register with `middleware=[use_low_temperature, time_model_calls, log_tool_calls]`.
Use this setting only with a model that supports temperature. `override` creates
an updated request without mutating the original; copying the settings preserves
other options. The handler returns a model response, which this wrapper forwards.

For a typical turn with one tool call, execution looks like this:

```text
wrap_model_call -> model requests get_weather
wrap_tool_call  -> get_weather executes
wrap_model_call -> model reads the tool result and answers
```

A turn can make more model calls or call several tools. Tool wrappers run only
when a tool executes. For multiple wrappers of the same kind, the first entry
in `middleware` is the outermost: it starts first and finishes last.

[LangChain custom middleware documentation](https://docs.langchain.com/oss/python/langchain/middleware/custom)
