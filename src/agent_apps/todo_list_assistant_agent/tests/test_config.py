"""Keep this agent's model and summary settings isolated from other agents."""

import os
from unittest.mock import Mock

import pytest
from pydantic import SecretStr

from agent_apps.todo_list_assistant_agent import config
from agent_apps.todo_list_assistant_agent.agent import model
from agent_apps.todo_list_assistant_agent.config import agent as agent_settings
from agent_apps.todo_list_assistant_agent.config import app as app_config


def test_only_local_file_is_read_and_process_environment_is_unchanged(
    tmp_path, monkeypatch
):
    outer = tmp_path / "repository"
    agent = outer / "src" / "agent_apps" / "todo_list_assistant_agent"
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
    monkeypatch.setattr(app_config, "ENV_FILE", local)
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
    reader = Mock(wraps=app_config.read_env)
    monkeypatch.setattr(app_config, "read_env", reader)

    settings = config.load_config()
    model.create_model(settings.model)
    arguments = constructor.call_args.kwargs
    assert isinstance(arguments["api_key"], SecretStr)
    assert arguments["api_key"].get_secret_value() == "local-test-key"
    assert arguments["model"] == "local-model"
    assert arguments["base_url"] == "https://local.example.test"
    assert settings.agent is agent_settings.AGENT_CONFIG
    reader.assert_called_once_with(app_config.ENV_FILE)
    assert dict(os.environ) == before


def test_missing_local_file_does_not_fall_back_to_parent_or_global_env(
    tmp_path, monkeypatch
):
    (tmp_path / ".env").write_text("GROQ_API_KEY=parent-test-key\n", encoding="utf-8")
    monkeypatch.setattr(app_config, "ENV_FILE", tmp_path / "agent" / ".env")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "global-test-key")
    monkeypatch.setenv("SUMMARY_TRIGGER_TOKENS", "999")
    assert config.read_env() == {}
    with pytest.raises(ValueError, match="Set GROQ_API_KEY"):
        config.load_config()


def test_local_values_are_not_interpolated_from_global_env(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("AGENT_MODEL=${UNRELATED_MODEL}\n", encoding="utf-8")
    monkeypatch.setattr(app_config, "ENV_FILE", path)
    monkeypatch.setenv("UNRELATED_MODEL", "other-agent-model")
    assert config.read_env()["AGENT_MODEL"] == "${UNRELATED_MODEL}"


def test_model_factory_uses_supplied_settings_without_reading_env(monkeypatch):
    settings = config.ModelConfig(
        api_key=SecretStr("isolated-test-key"),
        model="explicit-model",
        base_url="https://explicit.example.test",
        temperature=0.2,
        timeout=45,
        max_retries=2,
    )
    reader = Mock(side_effect=AssertionError("The model factory must not read .env"))
    monkeypatch.setattr(app_config, "read_env", reader)
    constructor = Mock()
    monkeypatch.setattr(model, "ChatGroq", constructor)

    model.create_model(settings)

    reader.assert_not_called()
    constructor.assert_called_once_with(
        model=settings.model,
        api_key=settings.api_key,
        base_url=settings.base_url,
        temperature=0.2,
        timeout=45,
        max_retries=2,
    )


def test_application_config_loads_defaults_from_one_local_snapshot(
    tmp_path, monkeypatch
):
    local = tmp_path / ".env"
    local.write_text("GROQ_API_KEY=isolated-test-key\n", encoding="utf-8")
    monkeypatch.setattr(app_config, "ENV_FILE", local)
    reader = Mock(wraps=app_config.read_env)
    monkeypatch.setattr(app_config, "read_env", reader)

    settings = config.load_config()

    reader.assert_called_once_with(app_config.ENV_FILE)
    assert settings.model.model == "openai/gpt-oss-20b"
    assert settings.model.base_url == "https://api.groq.com"
    assert settings.model.temperature == 0
    assert settings.model.timeout == 30
    assert settings.model.max_retries == 1
    assert settings.agent is agent_settings.AGENT_CONFIG


def test_explicit_config_path_does_not_change_the_default_location(
    tmp_path, monkeypatch
):
    missing = tmp_path / "missing.env"
    local = tmp_path / "selected.env"
    local.write_text(
        "GROQ_API_KEY=isolated-test-key\nAGENT_MODEL=selected-model\n"
        "SUMMARY_TRIGGER_TOKENS=123\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(app_config, "ENV_FILE", missing)

    settings = config.load_config(local)

    assert settings.model.model == "selected-model"
    assert settings.agent is agent_settings.AGENT_CONFIG
    assert app_config.ENV_FILE == missing
    with pytest.raises(ValueError, match="Set GROQ_API_KEY"):
        config.load_config()
