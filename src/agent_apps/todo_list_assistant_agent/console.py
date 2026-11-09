"""Console menus, conversation input/output, and expected error messages."""

import json
import readline
import sqlite3
from collections.abc import Sequence

from groq import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError
from langgraph.types import Command, Interrupt

from .agent.errors import InputTypeError, InputValueError
from .agent.nodes.summarize import SummaryError


def describe_api_error(error: APIError) -> str:
    """Explain the final SDK failure without starting another retry layer."""
    if isinstance(error, AuthenticationError):
        return "Authentication failed. Check GROQ_API_KEY in the agent-local .env."
    if isinstance(error, PermissionDeniedError):
        return "Permission denied. Check your API key's access to the selected model."
    if isinstance(error, NotFoundError):
        return "Model or endpoint not found. Check AGENT_MODEL and GROQ_BASE_URL."
    if isinstance(error, (BadRequestError, UnprocessableEntityError)):
        return (
            "The provider rejected the request. Check the model's supported request "
            "format, tool arguments, and structured-output settings."
        )
    if isinstance(error, RateLimitError):
        return "The provider rate limit or quota was reached. Wait or check your quota before trying again."
    # APITimeoutError is also an APIConnectionError; check it first.
    if isinstance(error, APITimeoutError):
        return (
            "The model request timed out. Check the connection and configured timeout."
        )
    if isinstance(error, APIConnectionError):
        return "Could not connect to the model provider. Check your network and GROQ_BASE_URL."
    if isinstance(error, APIStatusError):
        if error.status_code >= 500:
            return "The model provider reported a server error. Try again later."
        return f"The provider request failed with HTTP {error.status_code}. Check its error details."
    return "The model API request failed. Check the provider's error details."


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


def review_approvals(
    pending: Sequence[Interrupt],
) -> dict[str, dict[str, bool]] | None:
    """Collect explicit decisions by interrupt ID; None leaves approvals pending."""
    decisions: dict[str, dict[str, bool]] = {}
    for item in pending:
        payload = item.value
        if not isinstance(payload, dict) or payload.get("kind") != "tool_approval":
            raise ValueError("Unsupported pending approval request.")
        print("------")
        print("Human approval required")
        print(f"Tool: {payload['tool_name']}")
        print(f"Call ID: {payload['tool_call_id']}")
        print("Arguments:")
        print(json.dumps(payload["args"], ensure_ascii=False, indent=2))
        while True:
            choice = input("Approve this call? [y/n/exit]: ").strip().casefold()
            if choice in {"exit", "quit"}:
                return None
            if choice in {"y", "yes", "n", "no"}:
                decisions[item.id] = {"approved": choice in {"y", "yes"}}
                break
            print("Enter y to approve, n to reject, or exit to leave it pending.")
        print("------")
    return decisions


def chat(graph, thread_id: str = "default") -> None:
    """Run new turns and resumes; fixed dependencies are already bound to the graph."""
    # Readline edits whole Unicode characters rather than individual UTF-8 bytes.
    # Readline history is separate from the graph's persisted conversation state.
    readline.set_auto_history(False)
    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id},
    }
    print("------")
    print("Todo List Assistant Agent is ready.\nType 'exit' to quit. ")
    print(f"Conversation: {thread_id}.")

    while True:
        try:
            # A failed or interrupted run may have a pending node. Finish it first,
            # without appending a new user message or repeating completed steps.
            snapshot = graph.get_state(config)
            if snapshot.next:
                if snapshot.interrupts:
                    # Approval is external input, not a new HumanMessage. Use the
                    # saved interrupt ID and the same conversation's thread_id.
                    decisions = review_approvals(snapshot.interrupts)
                    if decisions is None:
                        print(
                            "Approval is still pending. Reopen this conversation to review it."
                        )
                        break
                    result = graph.invoke(Command(resume=decisions), config=config)
                else:
                    # Ordinary failed work has no approval answer to supply.
                    print("Assistant: Resuming the unfinished turn.\n")
                    result = graph.invoke(None, config=config)
            else:
                print("------")
                text = input("You: ").strip()
                if text.casefold() in {"exit", "quit"}:
                    break
                if not text:
                    continue

                # A new user message starts a new allowance. Resumes above omit
                # counters, retaining the same turn's checkpointed usage.
                # MessagesState merges this new message with restored history.
                result = graph.invoke(
                    {
                        "messages": [HumanMessage(text)],
                        "model_calls_this_turn": 0,
                        "tool_calls_this_turn": 0,
                    },
                    config=config,
                )

            # Compare message IDs before and after this invocation. A new conversation
            # may have no saved messages, so the snapshot lookup defaults to [].
            old_ids = {message.id for message in snapshot.values.get("messages", [])}
            # The result contains the current messages after any summary removals
            # and the new user/model/tool messages added during this invocation.
            new_ids = {message.id for message in result["messages"]}
            # Report compaction only when a nonempty summary exists and either
            # the summary changed or some previously saved messages were removed.
            if result.get("summary") and (
                result["summary"] != snapshot.values.get("summary", "")
                # Set difference: IDs present before but absent afterward.
                # This also detects compaction when the summary text stays the same.
                or old_ids - new_ids
            ):
                # Summarization already happened in the graph; only show a notice here.
                print("------")
                print("Context: Earlier conversation summarized; recent turns kept.")
                print("------")
            if result.get("__interrupt__"):
                # Report any committed summary before moving to approval review.
                # A paused run has no final assistant answer to print yet.
                continue
            # Always print the final reply, whether or not compaction occurred.
            print(f"Assistant: {result['messages'][-1].text}\n")

        except (EOFError, KeyboardInterrupt):
            # Ctrl+D ends input; Ctrl+C interrupts input or graph execution.
            # Leave the chat loop so main() can close the saver's connection.
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
                f"Assistant: This turn failed. {describe_api_error(exc)} Details: {exc}\n"
            )
            break
        except sqlite3.Error as exc:
            print(
                f"Assistant: Database operation failed. Check the SQLite file or try again later. Details: {exc}\n"
            )
            break
        except SummaryError as exc:
            print(
                f"Assistant: Summary failed. Original messages were kept. Details: {exc}\n"
            )
            break
        except OSError as exc:
            print(
                f"Assistant: Storage access failed. Check the data files and permissions. Details: {exc}\n"
            )
            break
        except (InputValueError, InputTypeError) as exc:
            print(f"Assistant: Invalid input or stored todo data. Details: {exc}\n")
            break
        # Generic ValueError/TypeError and other unexpected exceptions propagate
        # with their traceback; only explicit validation errors are user-correctable.

    print(
        "Saved checkpoints are kept. Restart and select this conversation to continue."
    )
    print("Assistant: Goodbye!")
