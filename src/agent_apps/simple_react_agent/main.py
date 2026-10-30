"""Console entry point: create the model, build the graph, then run chat.

Calls are synchronous so execution is easy to follow. Chat history stays in memory;
study plans persist in SQLite.
"""

import readline
import sqlite3

from groq import APIError
from langchain_core.messages import HumanMessage
from langgraph.errors import GraphRecursionError

from .graph import build_graph
from .model import create_model


def chat(graph) -> None:
    """Block 4: read input, run a turn, and keep the complete message history."""
    # Readline edits whole Unicode characters rather than individual UTF-8 bytes.
    # Disable automatic input history; messages below holds conversation history.
    readline.set_auto_history(False)
    messages = []
    print(
        "Study Time Assistant is ready. Type 'exit' to quit. "
        "Chat history stays in memory; study plans are saved in SQLite."
    )

    while True:
        try:
            print("------")
            text = input("You: ").strip()
            if text.casefold() in {"exit", "quit"}:
                break
            if not text:
                continue

            # Supply the full history followed by the latest user message.
            # Limit graph steps to bound tool loops; steps are not tool-call counts.
            result = graph.invoke(
                {"messages": [*messages, HumanMessage(text)]},
                config={"recursion_limit": 20},
            )
            # Replace history with the complete result instead of appending it again.
            # Update only after success so an incomplete turn does not leak forward.
            messages = result["messages"]
            print(f"Assistant: {messages[-1].text}\n")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        except GraphRecursionError:
            print("Assistant: Too many tool steps this turn. Try a smaller request.\n")
        except APIError as exc:
            print(
                f"Assistant: This turn failed. Check your network, API key, or model settings. Details: {exc}\n"
            )
        except sqlite3.Error as exc:
            print(
                f"Assistant: Database operation failed. Check the SQLite file or try again later. Details: {exc}\n"
            )
        # Handle file access and explicit plan-validation errors.
        # Unexpected exceptions propagate with their traceback for debugging.
        except (OSError, ValueError, TypeError) as exc:
            print(
                f"Assistant: This turn failed. Check the study plan file or your input. Details: {exc}\n"
            )

    print("Assistant: Goodbye!")


def main() -> None:
    """Connect the model, graph, and console."""
    try:
        model = create_model()
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Startup failed: {exc}") from exc
    # Let graph construction errors propagate instead of reporting a config error.
    graph = build_graph(model)
    chat(graph)
