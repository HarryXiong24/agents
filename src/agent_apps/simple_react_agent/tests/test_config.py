"""Keep this agent's model and summary settings isolated from other agents."""

import os
from unittest.mock import Mock

import pytest
from pydantic import SecretStr

from agent_apps.simple_react_agent import config, model


def test_only_local_file_is_read_and_process_environment_is_unchanged(
    tmp_path, monkeypatch
):
    outer = tmp_path / "repository"
    agent = outer / "src" / "agent_apps" / "simple_react_agent"
    agent.mkdir(parents=True)
    (outer / ".env").write_text(
        "GROQ_API_KEY=outer-key\nAGENT_MODEL=outer-model\nSUMMARY_TRIGGER_TOKENS=999\n",
        encoding="utf-8",
    )
    local = agent / ".env"
    local.write_text(
        "GROQ_API_KEY=local-test-key\nAGENT_MODEL=local-model\n"
        "GROQ_BASE_URL=https://local.example.test\nSUMMARY_TRIGGER_TOKENS=123\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "ENV_FILE", local)
    monkeypatch.chdir(outer)
    for name in (
        "GROQ_API_KEY",
        "AGENT_MODEL",
        "GROQ_BASE_URL",
        "SUMMARY_TRIGGER_TOKENS",
    ):
        monkeypatch.setenv(name, "unrelated-global-value")
    before = dict(os.environ)
    constructor = Mock()
    monkeypatch.setattr(model, "ChatGroq", constructor)

    model.create_model()
    arguments = constructor.call_args.kwargs
    assert isinstance(arguments["api_key"], SecretStr)
    assert arguments["api_key"].get_secret_value() == "local-test-key"
    assert arguments["model"] == "local-model"
    assert arguments["base_url"] == "https://local.example.test"
    assert config.load_summary_config().trigger_tokens == 123
    assert dict(os.environ) == before


def test_missing_local_file_does_not_fall_back_to_parent_or_global_env(
    tmp_path, monkeypatch
):
    (tmp_path / ".env").write_text("GROQ_API_KEY=parent-test-key\n", encoding="utf-8")
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / "agent" / ".env")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "global-test-key")
    monkeypatch.setenv("SUMMARY_TRIGGER_TOKENS", "999")
    assert config.read_env() == {}
    assert config.load_summary_config().trigger_tokens == 500
    with pytest.raises(ValueError, match="Set GROQ_API_KEY"):
        model.create_model()


def test_local_values_are_not_interpolated_from_global_env(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("AGENT_MODEL=${UNRELATED_MODEL}\n", encoding="utf-8")
    monkeypatch.setattr(config, "ENV_FILE", path)
    monkeypatch.setenv("UNRELATED_MODEL", "other-agent-model")
    assert config.read_env()["AGENT_MODEL"] == "${UNRELATED_MODEL}"
