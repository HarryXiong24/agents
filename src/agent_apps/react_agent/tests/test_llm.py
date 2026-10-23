"""Offline checks for Groq configuration and optional memory embeddings."""

from dataclasses import replace

import pytest
from langchain_groq import ChatGroq

from agent_apps.react_agent.agent import llm
from agent_apps.react_agent.agent.tools import calculator


def test_groq_model_supports_tool_binding(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(llm, "settings", replace(
        llm.settings, model="test-model", base_url="https://groq.example", temperature=0.1,
    ))

    model = llm.get_chat_model()

    assert isinstance(model, ChatGroq)
    assert model.model_name == "test-model"
    assert model.groq_api_base == "https://groq.example"
    assert model.groq_api_key.get_secret_value() == "test-key"
    assert model.temperature == 0.1
    assert model.bind_tools([calculator]).kwargs["tools"][0]["function"]["name"] == "calculator"


def test_missing_groq_key_has_actionable_error(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(ValueError, match="Set GROQ_API_KEY"):
        llm.get_chat_model()


def test_optional_embeddings_use_separate_ollama_endpoint(monkeypatch):
    monkeypatch.setattr(llm, "settings", replace(llm.settings, embed_model=None))
    assert llm.get_embeddings() is None

    monkeypatch.setattr(llm, "settings", replace(
        llm.settings,
        embed_model="nomic-embed-text",
        base_url="https://groq.example",
        embed_base_url="http://localhost:11434",
    ))
    embeddings = llm.get_embeddings()
    assert embeddings.model == "nomic-embed-text"
    assert embeddings.base_url == "http://localhost:11434"
