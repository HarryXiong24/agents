"""Check error classification and SDK-only retries with local mock HTTP transport."""

import sqlite3
from unittest.mock import Mock

import httpx
import pytest
from groq import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)
from langchain_core.messages import HumanMessage
from langchain_groq import ChatGroq
from pydantic import SecretStr

from agent_apps.todo_list_assistant_create_agent import console
from agent_apps.todo_list_assistant_create_agent.agent import memory
from agent_apps.todo_list_assistant_create_agent.agent import model as model_module
from agent_apps.todo_list_assistant_create_agent.agent.agent import build_agent
from agent_apps.todo_list_assistant_create_agent.agent.errors import (
    InputTypeError,
    InputValueError,
)
from agent_apps.todo_list_assistant_create_agent.agent.middleware.tool_execution import (
    handle_tool_error,
)
from agent_apps.todo_list_assistant_create_agent.config import ModelConfig


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DATABASE_FILE", tmp_path / "todos.sqlite")


@pytest.mark.parametrize(
    "error",
    [
        ValueError("Bug"),
        TypeError("Bug"),
        RuntimeError("Bug"),
        OSError("Disk"),
        sqlite3.OperationalError("Locked"),
    ],
)
def test_handler_propagates_operational_and_unmarked_program_errors(error):
    with pytest.raises(type(error)) as caught:
        handle_tool_error(error)
    assert caught.value is error


@pytest.mark.parametrize(
    "error",
    [InputValueError("Invalid date."), InputTypeError("Minutes must be an integer.")],
)
def test_handler_explains_only_marked_input_errors(error):
    text = handle_tool_error(error)
    assert "Tool input is invalid" in text
    assert str(error) in text


@pytest.mark.parametrize(
    ("status", "error_class", "advice"),
    [
        (400, BadRequestError, "supported request format"),
        (401, AuthenticationError, "GROQ_API_KEY"),
        (403, PermissionDeniedError, "Permission denied"),
        (404, NotFoundError, "AGENT_MODEL"),
        (422, UnprocessableEntityError, "structured-output"),
        (429, RateLimitError, "rate limit or quota"),
        (503, InternalServerError, "server error"),
    ],
)
def test_console_explains_final_provider_failure(
    monkeypatch, capsys, status, error_class, advice
):
    request = httpx.Request("POST", "https://example.test")
    response = httpx.Response(status, request=request)
    error = error_class("Simulated provider failure", response=response, body=None)
    graph = Mock()
    graph.get_state.return_value.next = ()
    graph.get_state.return_value.values = {}
    graph.invoke.side_effect = error
    monkeypatch.setattr("builtins.input", lambda _: "Hello")
    console.chat(graph)
    assert advice in capsys.readouterr().out
    graph.invoke.assert_called_once()


@pytest.mark.parametrize(
    ("error_class", "advice"),
    [(APIConnectionError, "Could not connect"), (APITimeoutError, "timed out")],
)
def test_connection_and_timeout_advice_are_distinct(error_class, advice):
    error = error_class(request=httpx.Request("POST", "https://example.test"))
    assert advice in console.describe_api_error(error)


def completion():
    return {
        "id": "offline",
        "object": "chat.completion",
        "created": 1,
        "model": "offline-model",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "Hello."},
            }
        ],
    }


def offline_model(monkeypatch, client, retries):
    def create(**kwargs):
        return ChatGroq(http_client=client, **kwargs)

    monkeypatch.setattr(model_module, "ChatGroq", create)
    return model_module.create_model(
        ModelConfig(
            api_key=SecretStr("offline-key"),
            model="offline-model",
            base_url="https://example.test",
            max_retries=retries,
        )
    )


@pytest.mark.parametrize(
    ("retries", "sequence"),
    [
        (1, [500, 200]),
        (1, [429, 200]),
        (1, ["connection", 200]),
        (1, ["timeout", 200]),
        (2, [429, 500, 200]),
    ],
)
def test_sdk_retry_success_is_one_completed_react_call(monkeypatch, retries, sequence):
    requests = []
    sleep = Mock()
    monkeypatch.setattr("groq._base_client.time.sleep", sleep)

    def respond(request):
        outcome = sequence[len(requests)]
        requests.append(request)
        if outcome == "connection":
            raise httpx.ConnectError("Offline connection failure", request=request)
        if outcome == "timeout":
            raise httpx.ReadTimeout("Offline timeout", request=request)
        if outcome == 200:
            return httpx.Response(200, json=completion())
        return httpx.Response(
            outcome,
            json={"error": {"message": "Temporary failure"}},
            headers={"retry-after": "0.001"},
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = build_agent(offline_model(monkeypatch, client, retries)).invoke(
            {
                "messages": [HumanMessage("Hello.")],
                "model_calls_this_turn": 0,
                "tool_calls_this_turn": 0,
            }
        )
    assert result["messages"][-1].text == "Hello."
    assert result["model_calls_this_turn"] == 1
    assert result["tool_calls_this_turn"] == 0
    assert len(requests) == len(sequence)
    assert sleep.call_count == len(sequence) - 1
    if isinstance(sequence[0], int):
        assert sleep.call_args_list[0].args[0] == 0.001


@pytest.mark.parametrize(
    ("status", "error_class", "attempts"),
    [
        (400, BadRequestError, 1),
        (401, AuthenticationError, 1),
        (403, PermissionDeniedError, 1),
        (404, NotFoundError, 1),
        (422, UnprocessableEntityError, 1),
        (429, RateLimitError, 2),
        (500, InternalServerError, 2),
    ],
)
def test_sdk_stops_at_configured_limit_and_does_not_retry_normal_4xx(
    monkeypatch, status, error_class, attempts
):
    requests = []
    sleep = Mock()
    monkeypatch.setattr("groq._base_client.time.sleep", sleep)

    def respond(request):
        requests.append(request)
        return httpx.Response(
            status,
            json={"error": {"message": "Simulated failure"}},
            headers={"retry-after": "0.001"},
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        graph = build_agent(offline_model(monkeypatch, client, 1))
        with pytest.raises(error_class):
            graph.invoke({"messages": [HumanMessage("Hello.")]})
    assert len(requests) == attempts
    assert sleep.call_count == attempts - 1
