"""The Gradio web UI."""

import gradio as gr

from .agent import Agent
from .config import MODEL, PROVIDER
from .styles import CSS, EXAMPLES, JS


def main():
    """Create the agent and open the chat UI in a browser."""
    # Worth printing: once several providers are configured, the only way to
    # tell which one answered you is to say so up front.
    print(f"Provider: {PROVIDER}  |  Model: {MODEL}", flush=True)
    agent = Agent()
    # gradio passes history as a list of {"role", "content"} dicts, which is
    # the same format the model API uses, so agent.chat can be handed over as is.
    gr.ChatInterface(
        agent.chat,
        title="Resume Digging Agent",
        description="Chat with resume digging agent about career, background and experience.",
        examples=EXAMPLES,
    ).launch(css=CSS, js=JS, theme=gr.themes.Base(), inbrowser=True)
