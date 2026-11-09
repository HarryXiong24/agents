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
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_groq import ChatGroq
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import SecretStr

from agent_apps.todo_list_assistant_agent import console
from agent_apps.todo_list_assistant_agent.agent import memory, middleware
from agent_apps.todo_list_assistant_agent.agent import model as model_module
from agent_apps.todo_list_assistant_agent.agent.errors import (
    InputTypeError,
    InputValueError,
)
from agent_apps.todo_list_assistant_agent.agent.graph import build_graph
from agent_apps.todo_list_assistant_agent.config import AgentConfig, ModelConfig
from agent_apps.todo_list_assistant_agent.config import agent as agent_settings


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
        middleware.handle_tool_error(error)
    assert caught.value is error


@pytest.mark.parametrize(
    "error",
    [InputValueError("Invalid date."), InputTypeError("Minutes must be an integer.")],
)
def test_handler_explains_only_marked_input_errors(error):
    text = middleware.handle_tool_error(error)
    assert "Tool input is invalid" in text
    assert str(error) in text


@pytest.mark.parametrize("minutes", [True, False, "30", 30.0])
def test_save_tool_rejects_coercible_noninteger_minutes_before_writing(
    monkeypatch, minutes
):
    write = Mock(wraps=memory.save_todo)
    monkeypatch.setattr(memory, "save_todo", write)
    model = Mock(spec=BaseChatModel)
    model.bind_tools.return_value = model
    model.invoke.side_effect = [
        AIMessage(
            "",
            tool_calls=[
                {
                    "name": "save_todo",
                    "args": {
                        "project": "Walk",
                        "minutes": minutes,
                        "date": "2026-11-09",
                    },
                    "id": "invalid-duration",
                }
            ],
        ),
        AIMessage("Please supply an integer duration."),
    ]
    result = build_graph(model).invoke({"messages": [HumanMessage("Save Walk.")]})
    message = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert message.status == "error"
    assert "minutes" in message.text
    assert result["tool_calls_this_turn"] == 1
    write.assert_not_called()
    assert memory.load_todos() == []


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
        result = build_graph(offline_model(monkeypatch, client, retries)).invoke(
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
        graph = build_graph(offline_model(monkeypatch, client, 1))
        with pytest.raises(error_class):
            graph.invoke({"messages": [HumanMessage("Hello.")]})
    assert len(requests) == attempts
    assert sleep.call_count == attempts - 1


def test_failed_write_is_not_automatically_retried_or_hidden(monkeypatch, tmp_path):
    write = Mock(side_effect=OSError("Disk unavailable"))
    monkeypatch.setattr(memory, "save_todo", write)
    model = Mock(spec=BaseChatModel)
    model.bind_tools.return_value = model
    model.invoke.return_value = AIMessage(
        "",
        tool_calls=[
            {
                "name": "save_todo",
                "args": {"project": "Walk", "minutes": 20, "date": "2026-11-09"},
                "id": "save",
            }
        ],
    )
    config: RunnableConfig = {"configurable": {"thread_id": "write-failure"}}
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_graph(model, saver)
        with pytest.raises(OSError, match="Disk unavailable"):
            graph.invoke(
                {
                    "messages": [HumanMessage("Save Walk.")],
                    "model_calls_this_turn": 0,
                    "tool_calls_this_turn": 0,
                },
                config,
            )
        state = graph.get_state(config)
        assert state.next == ("tools",)
        assert state.values["model_calls_this_turn"] == 1
        assert state.values["tool_calls_this_turn"] == 0
    write.assert_called_once()
    model.invoke.assert_called_once()


def test_resume_after_storage_failure_reuses_completed_write(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_settings, "AGENT_CONFIG", AgentConfig(approval_tools=()))
    memory.save_todo("Remove", 10, "2026-11-09")
    real_save, real_delete = memory.save_todo, memory.delete_todo
    save = Mock(wraps=real_save)
    failure = Mock(side_effect=OSError("Delete failed"))
    monkeypatch.setattr(memory, "save_todo", save)
    monkeypatch.setattr(memory, "delete_todo", failure)
    model = Mock(spec=BaseChatModel)
    model.bind_tools.return_value = model
    model.invoke.return_value = AIMessage(
        "",
        tool_calls=[
            {
                "name": "save_todo",
                "args": {"project": "Keep", "minutes": 20, "date": "2026-11-09"},
                "id": "save",
            },
            {
                "name": "delete_todo",
                "args": {"project": "Remove", "date": "2026-11-09"},
                "id": "delete",
            },
        ],
    )
    config: RunnableConfig = {"configurable": {"thread_id": "partial-write"}}
    database = str(tmp_path / "checkpoints.sqlite")
    with SqliteSaver.from_conn_string(database) as saver:
        with pytest.raises(OSError, match="Delete failed"):
            build_graph(model, saver).invoke(
                {
                    "messages": [HumanMessage("Save Keep, delete Remove.")],
                    "model_calls_this_turn": 0,
                    "tool_calls_this_turn": 0,
                },
                config,
            )
    save.assert_called_once()
    failure.assert_called_once()
    monkeypatch.setattr(memory, "delete_todo", real_delete)
    recovered = Mock(spec=BaseChatModel)
    recovered.bind_tools.return_value = recovered
    recovered.invoke.return_value = AIMessage("Done.")
    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_graph(recovered, saver)
        result = graph.invoke(None, config)
        assert graph.get_state(config).next == ()
        assert result["tool_calls_this_turn"] == 2
    save.assert_called_once()
    assert [todo["project"] for todo in memory.load_todos()] == ["Keep"]
