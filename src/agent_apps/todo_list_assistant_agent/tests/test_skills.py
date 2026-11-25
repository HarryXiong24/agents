"""Exercise skill loading and progressive disclosure through the real graph."""

from dataclasses import replace

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver

from agent_apps.todo_list_assistant_agent.agent import memory
from agent_apps.todo_list_assistant_agent.agent.graph import build_graph
from agent_apps.todo_list_assistant_agent.agent.skills import (
    MAX_FILE_BYTES,
    SkillLoadError,
    load_skills,
)
from agent_apps.todo_list_assistant_agent.agent.state import add_active_skills
from agent_apps.todo_list_assistant_agent.agent.tools import create_tools
from agent_apps.todo_list_assistant_agent.config import SKILLS_DIR, AgentConfig
from agent_apps.todo_list_assistant_agent.config import agent as agent_settings

from .helpers import CONFIG, TODO, ask, call, make_model

BODY = "# Demo\n\nFollow the demo workflow."


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DATABASE_FILE", tmp_path / "todos.sqlite")
    monkeypatch.setattr(
        agent_settings, "AGENT_CONFIG", AgentConfig(summary_trigger_tokens=100_000)
    )


def write_skill(root, name="demo", text=None, files=None):
    directory = root / name
    directory.mkdir(parents=True)
    if text is None:
        text = f"---\nname: {name}\ndescription: Demo skill for {name}.\n---\n{BODY}\n"
    (directory / "SKILL.md").write_text(text, encoding="utf-8")
    for path, content in (files or {}).items():
        target = directory / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return directory


@pytest.fixture
def skills(tmp_path):
    root = tmp_path / "skills"
    write_skill(root, files={"references/guide.md": "Guide text."})
    write_skill(root, "other")
    return load_skills(root)


def test_shipped_skills_are_valid():
    skills = load_skills(SKILLS_DIR)
    assert set(skills) == {"study-plan", "todo-cleanup"}
    assert list(skills["study-plan"].resources) == ["references/session-guide.md"]


def test_loader_reads_metadata_body_and_text_references_only(tmp_path):
    root = tmp_path / "skills"
    write_skill(
        root,
        files={
            "references/guide.md": "Guide.",
            "references/.hidden.md": "Hidden.",
            "references/data.bin": "Binary.",
            "scripts/run.md": "Not a reference.",
        },
    )
    (root / "_drafts").mkdir()
    skill = load_skills(root)["demo"]
    assert skill.description == "Demo skill for demo."
    assert skill.instructions == BODY
    assert dict(skill.resources) == {"references/guide.md": "Guide."}
    assert load_skills(tmp_path / "missing") == {}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (BODY, "must start"),
        ("---\nname: demo\n", "no closing"),
        ("---\nname: [demo\n---\nBody", "invalid YAML"),
        ("---\n- demo\n---\nBody", "mapping"),
        ("---\nname: Demo_Skill\ndescription: x\n---\nBody", "lowercase"),
        ("---\nname: elsewhere\ndescription: x\n---\nBody", "match its directory"),
        ("---\nname: demo\ndescription: '  '\n---\nBody", "description"),
        ("---\nname: demo\ndescription: " + "x" * 1025 + "\n---\nBody", "exceeds"),
        ("---\nname: demo\ndescription: x\n---\n\n", "no instructions"),
        ("---\nname: demo\ndescription: x\n---\n" + "x" * MAX_FILE_BYTES, "bytes"),
    ],
)
def test_malformed_skill_stops_loading(tmp_path, text, message):
    write_skill(tmp_path, text=text)
    with pytest.raises(SkillLoadError, match=message):
        load_skills(tmp_path)


def test_missing_skill_file_and_escaping_reference_are_rejected(tmp_path):
    (tmp_path / "empty" / "empty").mkdir(parents=True)
    with pytest.raises(SkillLoadError, match="no SKILL.md"):
        load_skills(tmp_path / "empty")
    outside = tmp_path / "secret.md"
    outside.write_text("Secret.", encoding="utf-8")
    directory = write_skill(tmp_path / "linked")
    (directory / "references").mkdir()
    (directory / "references" / "secret.md").symlink_to(outside)
    with pytest.raises(SkillLoadError, match="outside"):
        load_skills(tmp_path / "linked")


def test_catalog_first_then_instructions_after_load(skills):
    model = make_model(
        responses=[
            AIMessage("", tool_calls=[call("load_skill", {"name": "demo"}, "load")]),
            AIMessage(
                "",
                tool_calls=[
                    call(
                        "read_skill_file",
                        {"name": "demo", "path": "references/guide.md"},
                        "read",
                    )
                ],
            ),
            AIMessage("Done."),
        ]
    )
    result = build_graph(model, skills=skills).invoke(ask("Use the demo skill."))
    first, second, third = (
        item.args[0][0].text for item in model.invoke.call_args_list
    )
    # Level 1: catalog only. Todo context from ContextMiddleware is kept.
    assert "`demo`: Demo skill for demo." in first
    assert "`other`" in first
    assert "Current todo list" in first
    assert BODY not in first
    # Level 2: instructions and file list after load_skill.
    assert BODY in second and "references/guide.md" in second
    assert "Current todo list" in second
    assert result["active_skills"] == ["demo"]
    read = next(
        m
        for m in result["messages"]
        if isinstance(m, ToolMessage) and m.name == "read_skill_file"
    )
    assert read.text == "Guide text."
    assert BODY in third
    assert [r["tool_name"] for r in result["tool_history"]] == [
        "load_skill",
        "read_skill_file",
    ]
    assert result["tool_calls_this_turn"] == 2


@pytest.mark.parametrize(
    ("tool_call", "message"),
    [
        (call("load_skill", {"name": "missing"}), "Available skills: demo, other"),
        (
            call("read_skill_file", {"name": "demo", "path": "references/guide.md"}),
            "before reading",
        ),
    ],
)
def test_invalid_skill_requests_are_visible_input_errors(skills, tool_call, message):
    model = make_model(
        responses=[AIMessage("", tool_calls=[tool_call]), AIMessage("Sorry.")]
    )
    result = build_graph(model, skills=skills).invoke(ask())
    error = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert error.status == "error"
    assert message in error.text
    assert result.get("active_skills", []) == []


def test_active_skills_persist_across_turns_and_stay_bounded(skills, tmp_path):
    with SqliteSaver.from_conn_string(str(tmp_path / "cp.sqlite")) as saver:
        model = make_model(
            responses=[
                AIMessage("", tool_calls=[call("load_skill", {"name": "demo"}, "a")]),
                AIMessage("Loaded."),
                AIMessage("Still here."),
            ]
        )
        graph = build_graph(model, saver, skills=skills)
        graph.invoke(ask("Load demo."), CONFIG)
        result = graph.invoke(ask("Next turn."), CONFIG)
    assert result["active_skills"] == ["demo"]
    assert BODY in model.invoke.call_args_list[-1].args[0][0].text


def test_active_skill_reducer_moves_reloads_to_end_and_truncates(monkeypatch):
    monkeypatch.setattr(
        agent_settings,
        "AGENT_CONFIG",
        replace(agent_settings.AGENT_CONFIG, max_active_skills=2),
    )
    assert add_active_skills(["a", "b"], ["a"]) == ["b", "a"]
    assert add_active_skills(["a", "b"], ["c"]) == ["b", "c"]
    assert add_active_skills([], ["a", "a"]) == ["a"]


def test_no_skills_means_no_skill_tools_or_prompt_section():
    model = make_model(responses=[AIMessage("Hi.")])
    build_graph(model).invoke(ask())
    assert "# Skills" not in model.invoke.call_args_list[0].args[0][0].text
    names = [t.name for t in create_tools()]
    assert "load_skill" not in names and "read_skill_file" not in names
    assert [t.name for t in create_tools(load_skills(SKILLS_DIR))][-2:] == [
        "load_skill",
        "read_skill_file",
    ]


def test_loaded_skill_does_not_bypass_delete_approval():
    memory.save_todo(TODO["project"], TODO["minutes"], TODO["date"])
    target = {"project": TODO["project"], "date": TODO["date"]}
    model = make_model(
        responses=[
            AIMessage(
                "", tool_calls=[call("load_skill", {"name": "todo-cleanup"}, "a")]
            ),
            AIMessage("", tool_calls=[call("delete_todo", target, "b")]),
        ]
    )
    result = build_graph(model, skills=load_skills(SKILLS_DIR)).invoke(
        ask("Clean up."), {"configurable": {"thread_id": "approval"}}
    )
    assert result["__interrupt__"]
    assert memory.load_todos() == [TODO]


@pytest.mark.parametrize("other", ["save_todo", "read_skill_file"])
def test_skill_loading_must_be_in_its_own_batch(skills, other):
    args = (
        TODO
        if other == "save_todo"
        else {"name": "demo", "path": "references/guide.md"}
    )
    model = make_model(
        responses=[
            AIMessage(
                "",
                tool_calls=[
                    call("load_skill", {"name": "demo"}, "load"),
                    call(other, args, "other"),
                ],
            ),
            AIMessage("Please load the skill separately."),
        ]
    )
    result = build_graph(model, skills=skills).invoke(ask())
    outputs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(outputs) == 2
    assert all(m.status == "error" and "alone" in m.text for m in outputs)
    assert result.get("active_skills", []) == []
    assert result["tool_calls_this_turn"] == 2
    assert memory.load_todos() == []


def test_loading_a_skill_respects_whole_batch_budget(skills, monkeypatch):
    monkeypatch.setattr(
        agent_settings, "AGENT_CONFIG", AgentConfig(max_tool_calls_per_turn=0)
    )
    model = make_model(
        responses=[AIMessage("", tool_calls=[call("load_skill", {"name": "demo"})])]
    )
    result = build_graph(model, skills=skills).invoke(ask())
    assert result.get("active_skills", []) == []
    assert result["messages"][-2].status == "error"
    assert "tool-call budget" in result["messages"][-1].text
    assert model.invoke.call_count == 1


def test_skills_survive_restart_and_summary_without_serializing_instructions(
    skills, tmp_path, monkeypatch
):
    from unittest.mock import Mock

    from langchain_core.messages import HumanMessage

    monkeypatch.setattr(
        agent_settings,
        "AGENT_CONFIG",
        AgentConfig(summary_trigger_tokens=1, summary_keep_turns=1),
    )
    database = str(tmp_path / "skills.sqlite")
    first = make_model(
        responses=[
            AIMessage("", tool_calls=[call("load_skill", {"name": "demo"}, "load")]),
            AIMessage("Loaded. " + "Discussed the project. " * 40),
            AIMessage("We can continue."),
        ]
    )
    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_graph(first, saver, skills=skills)
        result = graph.invoke(ask("Discuss the project. " * 40), CONFIG)
        original_ids = {m.id for m in result["messages"]}
        graph.invoke(ask("Next turn."), CONFIG)
    recovered = make_model()
    business = Mock()
    business.invoke.return_value = AIMessage("The skill is still available.")
    recovered.bind_tools.return_value = business
    recovered.invoke.side_effect = None
    recovered.invoke.return_value = AIMessage("Discussed the project and loaded demo.")
    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_graph(recovered, saver, skills=skills)
        result = graph.invoke(ask("Continue after restarting."), CONFIG)
        assert result["active_skills"] == ["demo"]
        assert original_ids - {m.id for m in result["messages"]}
        assert result["summary"]
        assert BODY in business.invoke.call_args.args[0][0].text
        assert len(result["tool_history"]) == 1
        assert BODY not in repr(graph.get_state(CONFIG).values)
        assert len([m for m in result["messages"] if isinstance(m, HumanMessage)]) == 2
    recovered.invoke.assert_called_once()


def test_reference_lookup_rejects_unknown_paths_for_an_active_skill(skills):
    model = make_model(
        responses=[
            AIMessage("", tool_calls=[call("load_skill", {"name": "demo"}, "load")]),
            AIMessage(
                "",
                tool_calls=[
                    call(
                        "read_skill_file",
                        {"name": "demo", "path": "../secret.md"},
                        "read",
                    )
                ],
            ),
            AIMessage("That reference is unavailable."),
        ]
    )
    result = build_graph(model, skills=skills).invoke(ask())
    message = result["messages"][-2]
    assert message.status == "error"
    assert "has no file" in message.text
