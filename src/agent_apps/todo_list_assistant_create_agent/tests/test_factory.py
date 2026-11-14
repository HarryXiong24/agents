"""Exercise the real create_agent loop with offline models and temporary storage."""

import json
import sqlite3
from dataclasses import replace
from typing import Any
from unittest.mock import Mock

import httpx
import pytest
from groq import APIConnectionError
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableConfig, RunnableLambda
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from pydantic import Field

from agent_apps.todo_list_assistant_create_agent import console
from agent_apps.todo_list_assistant_create_agent import main as app
from agent_apps.todo_list_assistant_create_agent.agent import checkpoints, memory
from agent_apps.todo_list_assistant_create_agent.agent.agent import build_agent
from agent_apps.todo_list_assistant_create_agent.agent.state import AgentState
from agent_apps.todo_list_assistant_create_agent.config import AgentConfig
from agent_apps.todo_list_assistant_create_agent.config import agent as agent_settings
from agent_apps.todo_list_assistant_create_agent.config import app as app_config

TODO: dict[str, Any] = {"project": "Python", "minutes": 30, "date": "2026-11-15"}
REQUEST = {"projects": ["Python"], "date": "2026-11-15", "max_minutes": 60}
CANDIDATE = {"todos": [TODO]}
CONFIG: RunnableConfig = {"configurable": {"thread_id": "offline"}}


class OfflineModel(BaseChatModel):
    """Keep main, summary, and structured calls independently inspectable."""

    responses: list[Any] = Field(default_factory=list)
    requests: list[Any] = Field(default_factory=list)
    summary_requests: list[Any] = Field(default_factory=list)
    draft_requests: list[Any] = Field(default_factory=list)
    candidate: Any = Field(default_factory=lambda: CANDIDATE)
    draft_error: Any = None
    finish_reason: str = "stop"
    parsing_error: Any = None

    @property
    def _llm_type(self):
        return "offline"

    def bind_tools(self, tools, **kwargs):
        return RunnableLambda(self.main_reply)

    def main_reply(self, messages):
        self.requests.append(messages)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.summary_requests.append(messages)
        return ChatResult(
            generations=[
                ChatGeneration(message=AIMessage("Earlier conversation summary."))
            ]
        )

    def with_structured_output(self, schema, **kwargs):
        assert kwargs == {"method": "json_mode", "include_raw": True}

        def generate(messages):
            self.draft_requests.append(messages)
            if self.draft_error is not None:
                raise self.draft_error
            return {
                "raw": AIMessage(
                    "JSON", response_metadata={"finish_reason": self.finish_reason}
                ),
                "parsed": self.candidate,
                "parsing_error": self.parsing_error,
            }

        return RunnableLambda(generate)


def call(name, args=None, id="call"):
    return {"name": name, "args": args or {}, "id": id}


def ask(text="Hello") -> AgentState:
    return {
        "messages": [HumanMessage(text)],
        "model_calls_this_turn": 0,
        "tool_calls_this_turn": 0,
        "recorded_tool_call_ids": [],
        "draft_reply": None,
    }


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DATABASE_FILE", tmp_path / "todos.sqlite")
    monkeypatch.setattr(
        agent_settings, "AGENT_CONFIG", AgentConfig(summary_trigger_tokens=100_000)
    )


@pytest.fixture
def saver(tmp_path):
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as value:
        yield value


def settings(monkeypatch, **updates):
    monkeypatch.setattr(
        agent_settings, "AGENT_CONFIG", replace(agent_settings.AGENT_CONFIG, **updates)
    )


def test_react_save_list_history_and_dynamic_prompt(saver):
    model = OfflineModel(
        responses=[
            AIMessage("", tool_calls=[call("save_todo", TODO, "save")]),
            AIMessage("", tool_calls=[call("list_todos", id="list")]),
            AIMessage("", tool_calls=[call("get_tool_history", id="history")]),
            AIMessage("Saved and listed."),
        ]
    )
    result = build_agent(model, saver).invoke(
        ask("Save, list and explain tools."), CONFIG
    )
    assert memory.load_todos() == [TODO]
    assert result["messages"][-1].text == "Saved and listed."
    assert result["model_calls_this_turn"] == 4
    assert result["tool_calls_this_turn"] == 3
    assert [r["tool_name"] for r in result["tool_history"]] == [
        "save_todo",
        "list_todos",
    ]
    history = next(
        m
        for m in result["messages"]
        if isinstance(m, ToolMessage) and m.name == "get_tool_history"
    )
    assert [r["tool_name"] for r in json.loads(history.text)] == [
        "save_todo",
        "list_todos",
    ]
    assert json.dumps([TODO], ensure_ascii=False, indent=2) in model.requests[1][0].text
    assert saver.get(CONFIG) is not None


@pytest.mark.parametrize("approved", [True, False])
def test_builtin_hitl_restart_preserves_budget_and_history(tmp_path, approved):
    memory.save_todo(TODO["project"], TODO["minutes"], TODO["date"])
    database = str(tmp_path / "approval.sqlite")
    model = OfflineModel(
        responses=[
            AIMessage(
                "",
                tool_calls=[
                    call("delete_todo", {"project": "Python", "date": TODO["date"]})
                ],
            )
        ]
    )
    with SqliteSaver.from_conn_string(database) as saver:
        result = build_agent(model, saver).invoke(ask("Delete Python"), CONFIG)
        interrupt = result["__interrupt__"][0]
        assert interrupt.value["action_requests"][0]["name"] == "delete_todo"
        assert memory.load_todos() == [TODO]
        assert result["tool_calls_this_turn"] == 1
    recovered = OfflineModel(responses=[AIMessage("Finished.")])
    with SqliteSaver.from_conn_string(database) as saver:
        agent = build_agent(recovered, saver)
        result = agent.invoke(
            Command(
                resume={
                    interrupt.id: {
                        "decisions": [
                            {"type": "approve"}
                            if approved
                            else {"type": "reject", "message": "Declined."}
                        ]
                    }
                }
            ),
            CONFIG,
        )
        assert agent.get_state(CONFIG).next == ()
        assert result["model_calls_this_turn"] == 2
        assert result["tool_calls_this_turn"] == 1
        assert len(result["tool_history"]) == 1
        assert (memory.load_todos() == []) is approved


def test_multiple_calls_declined_before_approval_or_writes(saver):
    model = OfflineModel(
        responses=[
            AIMessage(
                "",
                tool_calls=[
                    call("save_todo", TODO, "one"),
                    call(
                        "delete_todo",
                        {"project": "Python", "date": TODO["date"]},
                        "two",
                    ),
                ],
            ),
            AIMessage("", tool_calls=[call("save_todo", TODO, "single")]),
            AIMessage("Saved once."),
        ]
    )
    result = build_agent(model, saver).invoke(ask(), CONFIG)
    messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert [m.status for m in messages] == ["error", "error", "success"]
    assert "__interrupt__" not in result
    assert result["tool_calls_this_turn"] == 3
    assert memory.load_todos() == [TODO]


def test_tool_budget_rejects_whole_request_before_approval(monkeypatch, saver):
    settings(monkeypatch, max_tool_calls_per_turn=1)
    model = OfflineModel(
        responses=[
            AIMessage(
                "",
                tool_calls=[
                    call("save_todo", TODO, "one"),
                    call(
                        "delete_todo",
                        {"project": "Python", "date": TODO["date"]},
                        "two",
                    ),
                ],
            )
        ]
    )
    result = build_agent(model, saver).invoke(ask(), CONFIG)
    assert memory.load_todos() == []
    assert "__interrupt__" not in result
    assert "budget" in result["messages"][-1].text
    assert len(result["tool_history"]) == 2


def test_model_limit_ends_with_complete_tool_result_and_resets(monkeypatch, saver):
    settings(monkeypatch, max_model_calls_per_turn=1)
    model = OfflineModel(
        responses=[
            AIMessage("", tool_calls=[call("save_todo", TODO)]),
            AIMessage("New turn."),
        ]
    )
    agent = build_agent(model, saver)
    result = agent.invoke(ask(), CONFIG)
    assert "model-call limit" in result["messages"][-1].text
    assert result["messages"][-2].status == "success"
    assert len(result["tool_history"]) == 1
    result = agent.invoke(ask("Continue"), CONFIG)
    assert result["messages"][-1].text == "New turn."
    assert len(result["tool_history"]) == 1


@pytest.mark.parametrize("minutes", [True, "30", 30.0, 0])
def test_invalid_tool_input_is_visible_and_never_written(minutes):
    model = OfflineModel(
        responses=[
            AIMessage("", tool_calls=[call("save_todo", {**TODO, "minutes": minutes})]),
            AIMessage("Please correct duration."),
        ]
    )
    result = build_agent(model).invoke(ask())
    tool = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert tool.status == "error"
    assert memory.load_todos() == []


@pytest.mark.parametrize(
    "error",
    [
        OSError("Disk"),
        sqlite3.OperationalError("Locked"),
        RuntimeError("Bug"),
        ValueError("Bug"),
    ],
)
def test_tool_faults_propagate_once(monkeypatch, saver, error):
    write = Mock(side_effect=error)
    monkeypatch.setattr(memory, "save_todo", write)
    model = OfflineModel(
        responses=[AIMessage("", tool_calls=[call("save_todo", TODO)])]
    )
    agent = build_agent(model, saver)
    with pytest.raises(type(error), match=str(error)):
        agent.invoke(ask(), CONFIG)
    write.assert_called_once()
    assert agent.get_state(CONFIG).values["tool_calls_this_turn"] == 1


def test_draft_returns_one_final_reply_without_write_and_survives_restart(saver):
    model = OfflineModel(
        responses=[AIMessage("", tool_calls=[call("generate_todo_draft", REQUEST)])]
    )
    result = build_agent(model, saver).invoke(ask("Propose Python"), CONFIG)
    assert result["todo_draft"] == CANDIDATE
    assert memory.load_todos() == []
    assert len(model.requests) == len(model.draft_requests) == 1
    assert len(result["tool_history"]) == 1
    assert result["draft_reply"] is None
    assert result["messages"][-1].text.count("Todo draft") == 1
    assert "Not saved." in result["messages"][-1].text
    later = OfflineModel(
        responses=[
            AIMessage("", tool_calls=[call("save_todo", TODO, "save")]),
            AIMessage("Saved."),
        ]
    )
    result = build_agent(later, saver).invoke(ask("Save the proposed task"), CONFIG)
    assert json.dumps(CANDIDATE, ensure_ascii=False) in later.requests[0][0].text
    assert memory.load_todos() == [TODO]
    assert result["todo_draft"] == CANDIDATE


@pytest.mark.parametrize(
    "candidate",
    [
        {"todos": []},
        {"todos": [{**TODO, "project": "Wrong"}]},
        {"todos": [{**TODO, "date": "2026-11-16"}]},
        {"todos": [{**TODO, "minutes": 90}]},
        {"todos": [{**TODO, "minutes": True}]},
    ],
)
def test_invalid_new_draft_clears_previous_candidate(candidate, saver):
    model = OfflineModel(
        responses=[AIMessage("", tool_calls=[call("generate_todo_draft", REQUEST)])],
        candidate=candidate,
    )
    result = build_agent(model, saver).invoke(
        {**ask(), "todo_draft": CANDIDATE}, CONFIG
    )
    assert result["todo_draft"] is None
    assert "Could not create a valid draft" in result["messages"][-1].text
    assert memory.load_todos() == []


@pytest.mark.parametrize("reason", ["length", "max_tokens", "content_filter"])
def test_truncated_draft_is_not_presented_as_success(reason):
    model = OfflineModel(
        responses=[AIMessage("", tool_calls=[call("generate_todo_draft", REQUEST)])],
        finish_reason=reason,
    )
    result = build_agent(model).invoke(ask())
    assert result["todo_draft"] is None
    assert "Could not create" in result["messages"][-1].text


def test_draft_api_failure_resumes_without_main_model_or_double_charge(saver):
    model = OfflineModel(
        responses=[AIMessage("", tool_calls=[call("generate_todo_draft", REQUEST)])],
        draft_error=APIConnectionError(
            request=httpx.Request("POST", "https://example.test")
        ),
    )
    agent = build_agent(model, saver)
    with pytest.raises(APIConnectionError):
        agent.invoke({**ask(), "todo_draft": CANDIDATE}, CONFIG)
    assert agent.get_state(CONFIG).values["todo_draft"] is None
    recovered = OfflineModel()
    agent = build_agent(recovered, saver)
    result = agent.invoke(None, CONFIG)
    assert recovered.requests == []
    assert len(recovered.draft_requests) == 1
    assert result["todo_draft"] == CANDIDATE
    assert result["tool_calls_this_turn"] == 1


def test_builtin_summary_removes_old_messages_but_keeps_draft(monkeypatch, saver):
    settings(monkeypatch, summary_trigger_tokens=1, summary_keep_messages=2)
    model = OfflineModel(
        responses=[
            AIMessage("", tool_calls=[call("generate_todo_draft", REQUEST)]),
            AIMessage("Discussed."),
            AIMessage("Still available."),
        ]
    )
    agent = build_agent(model, saver)
    first = agent.invoke(ask("Propose Python"), CONFIG)
    old_ids = {m.id for m in first["messages"]}
    agent.invoke(ask("Discuss the draft"), CONFIG)
    result = agent.invoke(ask("What was proposed?"), CONFIG)
    assert old_ids - {m.id for m in result["messages"]}
    assert model.summary_requests
    assert result["todo_draft"] == CANDIDATE
    assert len(result["tool_history"]) == 1
    assert json.dumps(CANDIDATE, ensure_ascii=False) in model.requests[-1][0].text
    assert any("Earlier conversation summary." in m.text for m in result["messages"])


def test_console_review_payload(monkeypatch, saver, capsys):
    memory.save_todo(TODO["project"], TODO["minutes"], TODO["date"])
    model = OfflineModel(
        responses=[
            AIMessage(
                "",
                tool_calls=[
                    call("delete_todo", {"project": "Python", "date": TODO["date"]})
                ],
            ),
            AIMessage("Deleted."),
        ]
    )
    inputs = iter(["Delete Python", "y", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    console.chat(build_agent(model, saver), "offline")
    assert memory.load_todos() == []
    assert "Assistant: Deleted." in capsys.readouterr().out


def test_restart_after_model_failure_does_not_repeat_completed_save(saver, monkeypatch):
    write = Mock(wraps=memory.save_todo)
    monkeypatch.setattr(memory, "save_todo", write)
    model = OfflineModel(
        responses=[
            AIMessage("", tool_calls=[call("save_todo", TODO)]),
            APIConnectionError(request=httpx.Request("POST", "https://example.test")),
        ]
    )
    agent = build_agent(model, saver)
    with pytest.raises(APIConnectionError):
        agent.invoke(ask("Save Python"), CONFIG)
    assert agent.get_state(CONFIG).next
    recovered = OfflineModel(responses=[AIMessage("Saved.")])
    result = build_agent(recovered, saver).invoke(None, CONFIG)
    write.assert_called_once()
    assert result["model_calls_this_turn"] == 2
    assert result["tool_calls_this_turn"] == 1
    assert len(result["tool_history"]) == 1
    assert recovered.requests[0][-1].name == "save_todo"


def test_console_exit_during_approval_can_reopen_without_new_user_message(
    saver, monkeypatch, capsys
):
    memory.save_todo(TODO["project"], TODO["minutes"], TODO["date"])
    model = OfflineModel(
        responses=[
            AIMessage(
                "",
                tool_calls=[
                    call("delete_todo", {"project": "Python", "date": TODO["date"]})
                ],
            )
        ]
    )
    inputs = iter(["Delete Python", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    console.chat(build_agent(model, saver), "offline")
    assert memory.load_todos() == [TODO]
    recovered = OfflineModel(responses=[AIMessage("Kept.")])
    inputs = iter(["n", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    agent = build_agent(recovered, saver)
    console.chat(agent, "offline")
    assert memory.load_todos() == [TODO]
    snapshot = agent.get_state(CONFIG)
    assert snapshot.next == ()
    assert (
        len([m for m in snapshot.values["messages"] if isinstance(m, HumanMessage)])
        == 1
    )
    assert snapshot.values["tool_calls_this_turn"] == 1
    assert "still pending" in capsys.readouterr().out


def test_history_retention_and_threads_share_only_todos(saver, monkeypatch):
    settings(monkeypatch, tool_history_limit=1)
    model = OfflineModel(
        responses=[
            AIMessage("", tool_calls=[call("save_todo", TODO, "one")]),
            AIMessage("", tool_calls=[call("list_todos", id="two")]),
            AIMessage("Done."),
            AIMessage("Separate conversation."),
        ]
    )
    agent = build_agent(model, saver)
    first = agent.invoke(ask("Save"), CONFIG)
    assert [r["tool_name"] for r in first["tool_history"]] == ["list_todos"]
    second = agent.invoke(ask("Hello"), {"configurable": {"thread_id": "other"}})
    assert len(second["messages"]) == 2
    assert second.get("tool_history", []) == []
    assert (
        json.dumps([TODO], ensure_ascii=False, indent=2) in model.requests[-1][0].text
    )
    assert checkpoints.list_threads(saver) == ["offline", "other"]


@pytest.mark.parametrize(
    "payload",
    [
        {**REQUEST, "projects": []},
        {**REQUEST, "projects": ["Python", "Python"]},
        {**REQUEST, "projects": ["Python", "English"], "max_minutes": 1},
        {**REQUEST, "max_minutes": True},
        {**REQUEST, "date": "2026-02-30"},
    ],
)
def test_invalid_draft_request_ends_without_generation_or_writes(payload):
    model = OfflineModel(
        responses=[AIMessage("", tool_calls=[call("generate_todo_draft", payload)])]
    )
    result = build_agent(model).invoke(ask())
    assert result["todo_draft"] is None
    assert "Could not create" in result["messages"][-1].text
    assert model.draft_requests == []
    assert memory.load_todos() == []


def test_main_menu_then_chat_and_restart_uses_own_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(
        checkpoints, "CHECKPOINTS_FILE", tmp_path / "data" / "checkpoints.sqlite"
    )
    monkeypatch.setattr(app_config, "ENV_FILE", tmp_path / ".env")
    app_config.ENV_FILE.write_text("GROQ_API_KEY=offline-test-key\n", encoding="utf-8")
    model = OfflineModel(responses=[AIMessage("Remembered."), AIMessage("Python.")])
    monkeypatch.setattr(app, "create_model", lambda config: model)
    inputs = iter(
        ["0", "python", "I like Python", "exit", "1", "What subject?", "exit"]
    )
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    app.main()
    app.main()
    assert [m.text for m in model.requests[-1][1:]] == [
        "I like Python",
        "Remembered.",
        "What subject?",
    ]
    with SqliteSaver.from_conn_string(str(checkpoints.CHECKPOINTS_FILE)) as saver:
        assert checkpoints.list_threads(saver) == ["python"]
        connection = saver.conn
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


def test_main_menu_exit_needs_no_credentials_or_model(tmp_path, monkeypatch):
    monkeypatch.setattr(
        checkpoints, "CHECKPOINTS_FILE", tmp_path / "data" / "checkpoints.sqlite"
    )
    monkeypatch.setattr(app_config, "ENV_FILE", tmp_path / ".env")
    create = Mock(side_effect=AssertionError("Must not create model"))
    monkeypatch.setattr(app, "create_model", create)
    monkeypatch.setattr("builtins.input", lambda _: "exit")
    app.main()
    create.assert_not_called()


def test_configuration_paths_are_separate_from_manual_agent():
    from agent_apps.todo_list_assistant_agent.config import app as original

    assert app_config.APP_DIR.name == "todo_list_assistant_create_agent"
    assert app_config.ENV_FILE != original.ENV_FILE
    assert app_config.DATA_DIR != original.DATA_DIR


def test_repeated_multicall_rejection_obeys_main_model_limit(monkeypatch):
    settings(monkeypatch, max_model_calls_per_turn=1)
    model = OfflineModel(
        responses=[
            AIMessage(
                "",
                tool_calls=[
                    call("save_todo", TODO, "one"),
                    call("save_todo", TODO, "two"),
                ],
            )
        ]
    )
    result = build_agent(model).invoke(ask())
    assert len(model.requests) == 1
    assert "model-call limit" in result["messages"][-1].text
    assert memory.load_todos() == []


def test_real_groq_draft_wrapper_uses_json_mode_and_hidden_runtime():
    from langchain_groq import ChatGroq
    from pydantic import SecretStr

    bodies = []

    def respond(request):
        body = json.loads(request.content)
        bodies.append(body)
        if len(bodies) == 1:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "draft",
                        "type": "function",
                        "function": {
                            "name": "generate_todo_draft",
                            "arguments": json.dumps(REQUEST),
                        },
                    }
                ],
            }
            finish_reason = "tool_calls"
        else:
            message = {"role": "assistant", "content": json.dumps(CANDIDATE)}
            finish_reason = "stop"
        return httpx.Response(
            200,
            json={
                "id": "offline",
                "object": "chat.completion",
                "created": 1,
                "model": "offline-model",
                "choices": [
                    {"index": 0, "finish_reason": finish_reason, "message": message}
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        model = ChatGroq(
            model="offline-model", api_key=SecretStr("offline-key"), http_client=client
        )
        result = build_agent(model).invoke(ask("Propose Python"))
    assert len(bodies) == 2
    assert result["todo_draft"] == CANDIDATE
    assert "Not saved." in result["messages"][-1].text
    assert bodies[1]["response_format"] == {"type": "json_object"}
    assert "tools" not in bodies[1]
    for description in bodies[0]["tools"]:
        assert "runtime" not in description["function"]["parameters"]["properties"]
    assert memory.load_todos() == []
