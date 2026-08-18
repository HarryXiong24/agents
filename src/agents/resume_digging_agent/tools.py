"""The tools the model is allowed to call, and the code that runs them.

A tool has two halves that must stay in sync:
  1. a JSON schema (in TOOLS) that describes it to the model
  2. a Python function (in TOOL_HANDLERS) that actually does the work
"""

import json

from openrouter.components import ChatToolCall

from .config import EMAILS_PATH


def record_email(email):
    """Append one visitor email address to the emails file, one per line.

    The string this returns is sent back to the model as the tool's result.
    """
    print(f"Tool called to record an email: {email}", flush=True)
    with EMAILS_PATH.open("a", encoding="utf-8") as file:
        file.write(email.strip() + "\n")
    return "Email received"

def show_email():
    """Show the recorded email addresses."""
    with EMAILS_PATH.open("r", encoding="utf-8") as file:
        emails = file.read().strip()
    return f"Recorded emails:\n{emails}"

# What the model sees. The model reads these descriptions to decide when to
# call the tool and what arguments to pass, so keep them clear.
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "record_email_tool",
            "description": "Use this tool to record that a user provided their email address",
            "parameters": {
                "type": "object",
                "properties": {
                    "email": {
                        "type": "string",
                        "description": "The email address of this user",
                    },
                },
                "required": ["email"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "show_email_tool",
            "description": "Use this tool to show the recorded email addresses",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    }
]

# Maps the tool name in the schema above to the function that implements it.
# Adding a second tool means adding one entry to TOOLS and one entry here.
TOOL_HANDLERS = {
    "record_email_tool": record_email,
    "show_email_tool": show_email
}


def run_tool_calls(tool_calls: list[ChatToolCall]) -> list[dict]:
    """Run every tool the model asked for and return the result messages.

    Each result must carry the tool_call_id it answers, so the model can match
    the result to the request it made.
    """
    results = []
    for tool_call in tool_calls:
        name = tool_call.function.name
        handler = TOOL_HANDLERS.get(name)
        if handler is None:
            # Tell the model instead of crashing - it can then try something else.
            content = f"Unknown tool: {name}"
        else:
            # The model sends arguments as a JSON string, e.g. '{"email": "a@b.com"}'.
            arguments = json.loads(tool_call.function.arguments or "{}")
            content = handler(**arguments) # Call the tool function with the arguments the model sent.
        results.append({"role": "tool", "content": content, "tool_call_id": tool_call.id})
    return results
