"""Exercise structured generation, requirement checks, State, and explicit saving offline."""

import json
from unittest.mock import Mock

import httpx
import pytest
from groq import APIConnectionError
from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_groq import ChatGroq
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from pydantic import SecretStr, ValidationError

from agent_apps.todo_list_assistant_agent import console
from agent_apps.todo_list_assistant_agent.agent import memory
from agent_apps.todo_list_assistant_agent.agent.graph import build_graph
from agent_apps.todo_list_assistant_agent.agent.nodes.draft import (
    DraftNode,
    validate_draft,
)
from agent_apps.todo_list_assistant_agent.agent.schemas import (
    TodoDraft,
    TodoDraftRequest,
)
from agent_apps.todo_list_assistant_agent.agent.state import AgentState
from agent_apps.todo_list_assistant_agent.agent.tools import generate_todo_draft
from agent_apps.todo_list_assistant_agent.config import AgentConfig
from agent_apps.todo_list_assistant_agent.config import agent as agent_settings

REQUEST = {"projects": ["Python", "English"], "date": "2026-11-09", "max_minutes": 90}
CANDIDATE = {
    "todos": [
        {"project": "Python", "minutes": 50, "date": "2026-11-09"},
        {"project": "English", "minutes": 30, "date": "2026-11-09"},
    ]
}


@pytest.fixture(autouse=True)
def isolate_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DATABASE_FILE", tmp_path / "todos.sqlite")


def draft_call(**updates):
    return {
        "name": "generate_todo_draft",
        "args": {**REQUEST, **updates},
        "id": "draft-request",
        "type": "tool_call",
    }


def make_model(*responses, candidate=None):
    model = Mock(spec=BaseChatModel)
    model.bind_tools.return_value = model
    model.invoke.side_effect = responses
    model.with_structured_output.return_value.invoke.return_value = {
        "raw": AIMessage("Internal JSON", response_metadata={"finish_reason": "stop"}),
        "parsed": CANDIDATE if candidate is None else candidate,
        "parsing_error": None,
    }
    return model


def test_successful_draft_is_internal_data_and_one_display_reply(
    tmp_path, monkeypatch, capsys
):
    memory.save_todo("Existing", 10, "2026-11-08")
    original = memory.load_todos()
    model = make_model(AIMessage("", tool_calls=[draft_call()]))
    config: RunnableConfig = {"configurable": {"thread_id": "proposal"}}
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_graph(model, saver)
        inputs = iter(
            ["Arrange Python and English within 90 minutes on 2026-11-09.", "exit"]
        )
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        console.chat(graph, "proposal")
        snapshot = graph.get_state(config)
        assert snapshot.next == ()
        assert snapshot.values["todo_draft"] == CANDIDATE
        assert len(snapshot.values["messages"]) == 4
        assert snapshot.values["messages"][-1].text.count("Todo draft") == 1
        assert snapshot.values["tool_history"][0]["tool_name"] == "generate_todo_draft"
    assert memory.load_todos() == original
    output = capsys.readouterr().out
    assert output.count("Assistant: Todo draft") == 1
    assert output.count("- Python: 50 minutes") == 1
    assert "Total: 80 / 90 minutes." in output
    assert "Not saved." in output
    model.invoke.assert_called_once()
    model.with_structured_output.assert_called_once_with(
        TodoDraft, method="json_mode", include_raw=True
    )
    messages = model.with_structured_output.return_value.invoke.call_args.args[0]
    assert "JSON Schema" in messages[0].text
    assert json.loads(messages[1].text) == REQUEST


@pytest.mark.parametrize(
    "overrides",
    [
        {"projects": []},
        {"projects": [" "]},
        {"projects": ["Python", "Python"]},
        {"projects": [" Python"]},
        {"date": "2026-02-30"},
        {"date": "20261109"},
        {"max_minutes": 0},
        {"max_minutes": 1441},
        {"max_minutes": True},
    ],
)
def test_invalid_request_constraints_are_rejected(overrides):
    with pytest.raises(ValidationError):
        TodoDraftRequest.model_validate({**REQUEST, **overrides})


def test_impossible_budget_is_rejected_before_generation():
    with pytest.raises(ValueError, match="one minute"):
        generate_todo_draft.invoke(draft_call(max_minutes=1))


@pytest.mark.parametrize(
    ("todos", "reason"),
    [
        (
            [
                {"project": "Python", "minutes": 70, "date": "2026-11-09"},
                {"project": "English", "minutes": 30, "date": "2026-11-09"},
            ],
            "exceeding",
        ),
        (
            [
                {"project": "Python", "minutes": 50, "date": "2026-11-10"},
                {"project": "English", "minutes": 30, "date": "2026-11-09"},
            ],
            "requested date",
        ),
        ([{"project": "Python", "minutes": 50, "date": "2026-11-09"}], "exactly once"),
        (
            [
                {"project": "Python", "minutes": 50, "date": "2026-11-09"},
                {"project": "Unexpected", "minutes": 30, "date": "2026-11-09"},
            ],
            "exactly once",
        ),
        (
            [
                {"project": "Python", "minutes": 10, "date": "2026-11-09"},
                {"project": "Python", "minutes": 10, "date": "2026-11-09"},
            ],
            "exactly once",
        ),
    ],
)
def test_structurally_valid_draft_can_fail_business_checks(todos, reason):
    draft = TodoDraft.model_validate({"todos": todos})
    with pytest.raises(ValueError, match=reason):
        validate_draft(draft, TodoDraftRequest.model_validate(REQUEST))
    model = make_model(AIMessage("", tool_calls=[draft_call()]), candidate=draft)
    result = build_graph(model).invoke({"messages": [HumanMessage("Draft only.")]})
    assert result["todo_draft"] is None
    assert reason in result["messages"][-1].text
    assert "Draft generation did not save any todos" in result["messages"][-1].text
    assert memory.load_todos() == []
    model.invoke.assert_called_once()


@pytest.mark.parametrize(
    "candidate",
    [
        {"todos": []},
        {"todos": [{"project": "Python", "minutes": "30", "date": "2026-11-09"}]},
        {**CANDIDATE, "reply": "unexpected"},
    ],
)
def test_invalid_model_structure_is_not_persisted_or_saved(candidate):
    model = make_model(AIMessage("", tool_calls=[draft_call()]), candidate=candidate)
    result = build_graph(model).invoke({"messages": [HumanMessage("Draft only.")]})
    assert result["todo_draft"] is None
    assert "Could not create a valid draft" in result["messages"][-1].text
    assert memory.load_todos() == []


def test_parse_failure_does_not_retry_or_write():
    model = make_model(AIMessage("", tool_calls=[draft_call()]))
    model.with_structured_output.return_value.invoke.side_effect = (
        OutputParserException("Invalid JSON")
    )
    result = build_graph(model).invoke({"messages": [HumanMessage("Draft only.")]})
    assert result["todo_draft"] is None
    assert "Draft generation did not save any todos" in result["messages"][-1].text
    model.with_structured_output.return_value.invoke.assert_called_once()


def test_mixed_draft_and_save_batch_is_rejected_before_side_effects():
    save_call = {"name": "save_todo", "args": CANDIDATE["todos"][0], "id": "save"}
    model = make_model(
        AIMessage("", tool_calls=[draft_call(), save_call]),
        AIMessage("I need to propose the draft separately."),
    )
    result = build_graph(model).invoke({"messages": [HumanMessage("Propose a draft.")]})
    outputs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(outputs) == 2
    assert all(m.status == "error" for m in outputs)
    assert memory.load_todos() == []
    model.with_structured_output.assert_not_called()


def test_new_invalid_request_clears_previous_proposal(tmp_path):
    model = make_model(
        AIMessage("", tool_calls=[draft_call()]),
        AIMessage("", tool_calls=[draft_call(max_minutes=1)]),
        AIMessage("That budget is too small."),
        AIMessage("Which earlier draft do you mean?"),
    )
    config: RunnableConfig = {"configurable": {"thread_id": "replace"}}
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_graph(model, saver)
        first = graph.invoke({"messages": [HumanMessage("Draft.")]}, config)
        assert first["todo_draft"] == CANDIDATE
        second = graph.invoke(
            {"messages": [HumanMessage("Try one minute instead.")]}, config
        )
        assert second["todo_draft"] is None
        graph.invoke({"messages": [HumanMessage("Can you save this draft?")]}, config)
        system = model.invoke.call_args.args[0][0].text
        assert "There is no active validated draft" in system
        assert "Do not treat historical proposals as current" in system
    model.with_structured_output.assert_called_once()


def test_checkpointed_draft_enters_next_turn_and_explicit_save_can_pause(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        agent_settings, "AGENT_CONFIG", AgentConfig(approval_tools=("save_todo",))
    )
    database = str(tmp_path / "checkpoints.sqlite")
    config: RunnableConfig = {"configurable": {"thread_id": "save-later"}}
    first = make_model(AIMessage("", tool_calls=[draft_call()]))
    with SqliteSaver.from_conn_string(database) as saver:
        build_graph(first, saver).invoke(
            {"messages": [HumanMessage("Draft only.")]}, config
        )
    assert memory.load_todos() == []
    save_call = {"name": "save_todo", "args": CANDIDATE["todos"][0], "id": "save"}
    later = make_model(
        AIMessage("", tool_calls=[save_call]), AIMessage("Saved Python.")
    )
    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_graph(later, saver)
        paused = graph.invoke(
            {"messages": [HumanMessage("Save Python from the draft.")]}, config
        )
        assert paused["__interrupt__"]
        assert memory.load_todos() == []
        system = later.invoke.call_args.args[0][0].text
        assert "Latest validated proposal" in system
        assert json.dumps(CANDIDATE, ensure_ascii=False) in system
        decision = {paused["__interrupt__"][0].id: {"approved": True}}
        result = graph.invoke(Command(resume=decision), config)
        assert result["todo_draft"] == CANDIDATE
        assert memory.load_todos() == [CANDIDATE["todos"][0]]
        assert graph.get_state(config).next == ()
    later.with_structured_output.assert_not_called()


def test_draft_api_failure_can_resume_without_repeating_request_tool(tmp_path):
    config: RunnableConfig = {"configurable": {"thread_id": "retry-draft"}}
    database = str(tmp_path / "checkpoints.sqlite")
    first = make_model(AIMessage("", tool_calls=[draft_call()]))
    first.with_structured_output.return_value.invoke.side_effect = APIConnectionError(
        request=httpx.Request("POST", "https://example.test")
    )
    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_graph(first, saver)
        with pytest.raises(APIConnectionError):
            graph.invoke({"messages": [HumanMessage("Draft only.")]}, config)
        assert graph.get_state(config).next == ("draft",)
    recovered = make_model()
    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_graph(recovered, saver)
        result = graph.invoke(None, config)
        assert result["todo_draft"] == CANDIDATE
        assert len(result["tool_history"]) == 1
        assert graph.get_state(config).next == ()
    recovered.invoke.assert_not_called()
    assert memory.load_todos() == []


def test_real_groq_wrapper_uses_json_mode_and_local_schema_validation():
    bodies = []

    def respond(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "draft-test",
                "object": "chat.completion",
                "created": 1,
                "model": "offline-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(CANDIDATE),
                        },
                    }
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        model = ChatGroq(
            model="offline-model", api_key=SecretStr("offline-key"), http_client=client
        )
        state: AgentState = {"messages": [generate_todo_draft.invoke(draft_call())]}
        result = DraftNode(model).draft(state)
    assert result["todo_draft"] == CANDIDATE
    assert len(bodies) == 1
    assert bodies[0]["response_format"] == {"type": "json_object"}
    assert "tools" not in bodies[0]
    assert "JSON Schema" in bodies[0]["messages"][0]["content"]


@pytest.mark.parametrize(
    "failure", ["length", "max_tokens", "content_filter", "parser"]
)
def test_incomplete_or_unparseable_response_is_not_presented_as_a_draft(failure):
    model = make_model(AIMessage("", tool_calls=[draft_call()]))
    output = model.with_structured_output.return_value.invoke.return_value
    if failure != "parser":
        output["raw"] = AIMessage(
            "Incomplete JSON", response_metadata={"finish_reason": failure}
        )
    else:
        output["parsing_error"] = OutputParserException("Invalid JSON")
    result = build_graph(model).invoke({"messages": [HumanMessage("Draft only.")]})
    assert result["todo_draft"] is None
    assert "Could not create a valid draft" in result["messages"][-1].text
    assert memory.load_todos() == []


def test_draft_failure_does_not_deny_or_undo_an_earlier_save():
    saved_todo = {"project": "Walk", "minutes": 10, "date": "2026-11-09"}
    model = make_model(
        AIMessage(
            "", tool_calls=[{"name": "save_todo", "args": saved_todo, "id": "save"}]
        ),
        AIMessage("", tool_calls=[draft_call()]),
        candidate={"todos": []},
    )
    result = build_graph(model).invoke(
        {
            "messages": [
                HumanMessage(
                    "Save Walk for 10 minutes on 2026-11-09, then propose a separate draft."
                )
            ]
        }
    )
    assert memory.load_todos() == [saved_todo]
    assert "Draft generation did not save any todos" in result["messages"][-1].text
    assert "Nothing was saved" not in result["messages"][-1].text
    assert result["todo_draft"] is None


def test_summary_removes_draft_messages_but_keeps_candidate_and_model_context(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        agent_settings,
        "AGENT_CONFIG",
        AgentConfig(summary_trigger_tokens=1, summary_keep_turns=1),
    )
    model = make_model()
    business_model = Mock()
    business_model.invoke.side_effect = [
        AIMessage("", tool_calls=[draft_call()]),
        AIMessage("We can discuss the proposed arrangement."),
        AIMessage("The latest draft remains available."),
    ]
    model.bind_tools.return_value = business_model
    model.invoke.side_effect = None
    model.invoke.return_value = AIMessage("Discussed an unsaved draft.")
    config: RunnableConfig = {"configurable": {"thread_id": "summary-draft"}}
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_graph(model, saver)
        first = graph.invoke({"messages": [HumanMessage("Propose a draft.")]}, config)
        draft_message_id = first["messages"][-1].id
        graph.invoke({"messages": [HumanMessage("Let's discuss it.")]}, config)
        result = graph.invoke(
            {"messages": [HumanMessage("What is the latest proposal?")]}, config
        )
        assert result["summary"] == "Discussed an unsaved draft."
        assert draft_message_id not in {m.id for m in result["messages"]}
        assert result["todo_draft"] == CANDIDATE
        assert graph.get_state(config).values["todo_draft"] == CANDIDATE
    system = business_model.invoke.call_args.args[0][0].text
    assert json.dumps(CANDIDATE, ensure_ascii=False) in system
    assert memory.load_todos() == []
    model.invoke.assert_called_once()
    model.with_structured_output.assert_called_once()
