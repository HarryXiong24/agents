"""The Gradio web UI."""

import gradio as gr

from .agent import Agent
from .styles import CSS, EXAMPLES, JS


def main():
    """Create the agent and open the chat UI in a browser."""
    agent = Agent()
    # gradio passes history as a list of {"role", "content"} dicts, which is
    # the same format the model API uses, so agent.chat can be handed over as is.
    gr.ChatInterface(
        agent.chat,
        title="Digital Twin",
        description="Chat with my AI twin about my career, background and experience.",
        examples=EXAMPLES,
    ).launch(css=CSS, js=JS, theme=gr.themes.Base(), inbrowser=True)
