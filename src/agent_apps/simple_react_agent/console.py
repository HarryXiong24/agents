"""Console menus, conversation input/output, and expected error messages."""

import readline
import sqlite3

from groq import APIError
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError


def select_thread(threads: list[str]) -> str | None:
    """Choose a saved conversation or name a new one; return None to exit."""
    # Keep terminal editing independent of checkpoint storage.
    readline.set_auto_history(False)
    choices = {str(index): thread for index, thread in enumerate(threads, start=1)}
    print("------")
    print("Conversations")
    if not threads:
        print("No saved conversations yet.")
    for number, thread in choices.items():
        print(f"{number}. {thread}")
    print("0. New conversation")
    print("\nType 'exit' to quit.")
    print("------")

    while True:
        choice = input("Choose a conversation: ").strip()
        if choice.casefold() in {"exit", "quit"}:
            return None
        if choice in choices:
            return choices[choice]
        if choice == "0":
            name = input("New conversation name (or 'exit' to quit): ").strip()
            if name.casefold() in {"exit", "quit"}:
                return None
            if not name:
                print("Conversation name must not be empty.")
            elif name in threads:
                print(
                    "That conversation already exists. Choose its number to continue."
                )
            else:
                # The first graph invocation creates its checkpoints automatically.
                return name
        else:
            print("Enter a listed number, 0 to create a conversation, or 'exit'.")


def chat(graph, thread_id: str = "default") -> None:
    """Send new messages; the checkpointer keeps history for this conversation."""
    # Readline edits whole Unicode characters rather than individual UTF-8 bytes.
    # Readline history is separate from the graph's persisted conversation state.
    readline.set_auto_history(False)
    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 20,
    }
    print("------")
    print("Study Time Assistant is ready.\nType 'exit' to quit. ")
    print(f"Conversation: {thread_id}.")

    while True:
        try:
            # A failed or interrupted run may have a pending node. Finish it first,
            # without appending a new user message or repeating completed steps.
            if graph.get_state(config).next:
                print("Assistant: Resuming the unfinished turn.\n")
                result = graph.invoke(None, config=config)
            else:
                print("------")
                text = input("You: ").strip()
                if text.casefold() in {"exit", "quit"}:
                    break
                if not text:
                    continue

                # Send only the new message. MessagesState merges it with the
                # history restored by the checkpointer for this thread_id.
                result = graph.invoke({"messages": [HumanMessage(text)]}, config=config)
            print(f"Assistant: {result['messages'][-1].text}\n")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        except GraphRecursionError:
            print(
                "Assistant: Too many tool steps this turn. "
                "Create a new conversation for a smaller request.\n"
            )
            break
        except APIError as exc:
            print(
                f"Assistant: This turn failed. Check your network, API key, or model settings. Details: {exc}\n"
            )
            break
        except sqlite3.Error as exc:
            print(
                f"Assistant: Database operation failed. Check the SQLite file or try again later. Details: {exc}\n"
            )
            break
        # Handle file access and explicit plan-validation errors.
        # Unexpected exceptions propagate with their traceback for debugging.
        except (OSError, ValueError, TypeError) as exc:
            print(
                f"Assistant: This turn failed. Check the study plan file or your input. Details: {exc}\n"
            )
            break

    print(
        "Saved checkpoints are kept. Restart and select this conversation to continue."
    )
    print("Assistant: Goodbye!")
