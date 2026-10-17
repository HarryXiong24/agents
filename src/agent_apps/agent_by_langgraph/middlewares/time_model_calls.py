from collections.abc import Callable
from time import perf_counter

from langchain.agents.middleware import ModelRequest, ModelResponse, wrap_model_call


@wrap_model_call
def time_model_calls(
    request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
) -> ModelResponse:
    """Time each model call; register with middleware=[time_model_calls].

    request carries the model, messages, tools, and model settings.
    handler(request) runs the next wrapper or the model itself. Return its
    response unchanged; finally also logs duration when the call raises.
    """
    started = perf_counter()
    try:
        return handler(request)
    finally:
        print(f"  [middleware] model call took {perf_counter() - started:.2f}s")
