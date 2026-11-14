# Todo List Assistant — create_agent

[简体中文](README.zh-CN.md)

A console todo assistant built with **LangChain `create_agent` and middleware**.
The sibling [manual LangGraph application](../todo_list_assistant_agent/README.md)
remains separate. This application has its own configuration and databases; it
neither imports nor changes the sibling application's personal data.

## Run

From the repository root:

```bash
uv sync --locked
cp src/agent_apps/todo_list_assistant_create_agent/.env.example src/agent_apps/todo_list_assistant_create_agent/.env
```

Set `GROQ_API_KEY` in this application's `.env`, then run:

```bash
uv run --locked todo-list-assistant-create-agent
```

Or, with the repository environment already installed:

```bash
.venv/bin/python -m agent_apps.todo_list_assistant_create_agent
```

Startup always opens a conversation menu. Select a saved conversation or enter
`0` and a new name. Enter `exit` or `quit` to leave. Browsing the menu and exiting
requires no API key. A conversation is persisted on its first invocation.
The terminal supports Chinese input and backspace; assistant replies default to
English unless another language is requested.

## Try it

- “Save Clean room for 30 minutes on 2026-11-15.”
- “List my todos on 2026-11-15.”
- “Update Clean room on 2026-11-15 to 45 minutes.”
- “Delete Clean room on 2026-11-15.” — choose `y` or `n` at approval.
- “Propose Python and English on 2026-11-16 within 90 minutes.”
- “Save Python from that draft.” — explicitly saves that proposed record.
- “Which tools ran, and what were their results?”

These are example requests, not recorded model traces. Actual tool selection and
wording depend on the configured model.

## Capabilities and data

| Capability | Behavior |
|---|---|
| Todo CRUD | Exactly `project` (name), `minutes` (integer, 1–1440), `date` (`YYYY-MM-DD`) |
| Update | Same name and date replaces duration; a new name/date adds a record |
| List | All records, or exact name/date filters; the model presents the tool result |
| Delete approval | Built-in HITL pauses `delete_todo` before execution |
| Conversation history | SQLite checkpointer stores State under the selected `thread_id` |
| Summaries | Built-in middleware replaces older messages with a summary message |
| Tool history | Retains the latest 10 completed or declined requests per conversation |
| Draft arrangement | Dedicated JSON-mode model call; Pydantic and business validation; no writes |
| Limits | Per-user-turn main-model and admitted-tool quotas, plus graph recursion limit |

Todos are shared across this application's conversations. Messages, proposals,
usage counters and tool history belong to each conversation. These are separate
from the sibling application's records. There is no status, priority, reminder,
rename, reschedule, multi-date draft, or calendar-conflict feature.

A generated draft checks exact task names, the requested date and total duration.
It appears once through a return-direct tool and a presentation hook. Ordinary
conversation remains free text. Creating a new draft clears the old candidate
before generation; invalid candidates are not retained. Saving a candidate does
not clear it. It remains a proposal, while the database is the saved-state source.

## Configuration and persistence

Only `config/app.py` reads the **application-local `.env`**. Parent `.env` files
and shell environment variables are not used for these model settings.

| Setting | Location | Default |
|---|---|---|
| `GROQ_API_KEY` | Local `.env` | Required for chat |
| `AGENT_MODEL` | Local `.env` | `openai/gpt-oss-20b` |
| `GROQ_BASE_URL` | Local `.env` | `https://api.groq.com` |
| `temperature` / `timeout` / `max_retries` | `config/model.py` | `0` / 30 seconds / 1 SDK retry |
| `summary_trigger_tokens` | `config/agent.py` | 500 estimated tokens |
| `summary_keep_messages` | `config/agent.py` | 6 recent messages, adjusted for tool pairs |
| `max_model_calls_per_turn` | `config/agent.py` | 6 successful main-model responses |
| `max_tool_calls_per_turn` | `config/agent.py` | 8 admitted requests |
| `tool_history_limit` | `config/agent.py` | 10 records |
| `approval_tools` | `config/agent.py` | `("delete_todo",)` |
| `recursion_limit` | `config/agent.py` | 80 graph steps |

Summary and structured-draft model calls are outside the main-model quota.
SDK HTTP retries do not add successful main-model responses. New console input
resets turn counters; checkpoint resumes preserve them. A request consumes a tool
slot before approval; rejection still consumes that slot. A multi-call response
within quota is declined in full and charged for its requests; the model can
reissue calls one at a time. An over-budget batch is declined without execution
or approval and ends the turn. Already committed work remains saved.

`summary_keep_messages` counts **messages, not conversation turns**. The 500-token
trigger is intentionally low for learning; it is approximate, not a guaranteed
four/five-turn trigger or a hard whole-request context cap. The built-in middleware
checks before each main-model call and preserves tool request/result boundaries.
Its summary is inside `messages`, so there is no custom `summary` State field.
Drafts and retained tool history survive removal of their original messages.

Ignored local files:

```text
.env
data/todos.sqlite
data/todo_checkpoints.sqlite
```

The checkpointer handles persistence during graph execution; `exit` closes the
resource, rather than initiating a special save. On restart, an approval is shown
again; other pending work is explicitly resumed before new input. There is no
application retry loop. Groq SDK retry behavior is controlled by `max_retries`;
the built-in summary middleware separately has a context-overflow fallback that
can make one additional summary request with less input. Failed tools propagate
unless their error is a recognized input error. Unexpected programming errors
retain their tracebacks. Checkpointing is not an exactly-once transaction across
SQLite todo writes and graph saves.

## Layout and reading order

```text
main.py / console.py         Resources, menu, chat, approval payloads
config/                      app.py, model.py, agent.py
agent/agent.py               create_agent and middleware composition
agent/middleware/            One module per middleware responsibility
agent/state.py               Custom fields and bounded history reducer
agent/tools/                 Tools grouped by capability; __init__.py assembles them
agent/schemas.py             Structured draft request and output schemas
agent/prompts.py             Markdown template loader
agent/prompt_templates/      Model-visible instructions
agent/memory.py              Todo SQLite CRUD
agent/checkpoints.py         Conversation list and checkpoint path
agent/errors.py              Shared input-validation exception types
```

```text
agent/middleware/
├── __init__.py
├── turn_control.py
├── history.py
├── context.py
├── tool_execution.py
└── draft_presentation.py
```

Read each middleware class in its own module; `__init__.py` only exports the
classes, while `agent.py` determines their composition order.
`middleware/tool_execution.py` also contains the `handle_tool_error()` helper
used to format recognized input errors.

```text
agent/tools/
├── __init__.py
├── time.py
├── calculator.py
├── todos.py
├── history.py
└── draft.py
```

`tools/__init__.py` defines `create_tools(model)`, which remains available through
`from .tools import create_tools`. Save/delete/list stay together in `todos.py`;
`draft.py` contains the model-bound draft tool, `DraftGenerator` and business
validation. `schemas.py` defines the Pydantic request/output models. Graph runtime
injection and all tool names, schemas and registration order remain unchanged.

Start with `agent.py`, then read `middleware/`, `tools/__init__.py`, `state.py`
and `tools/draft.py`. See the [comparison guide](docs/COMPARISON.md) for the control flow,
composition order and differences from the manual graph.

## Offline checks

From the repository root:

```bash
.venv/bin/python -m pytest -q src/agent_apps/todo_list_assistant_create_agent/tests -W error
.venv/bin/ruff check src/agent_apps/todo_list_assistant_create_agent
.venv/bin/ruff format --check src/agent_apps/todo_list_assistant_create_agent
uv tool run --from pyright pyright --pythonpath .venv/bin/python src/agent_apps/todo_list_assistant_create_agent
```

Tests use fake models, mock HTTP and temporary SQLite files. They cover real
factory/middleware execution, approvals and restart, quotas, summaries, drafts,
CRUD validation, SDK retries, local configuration and terminal editing. They do
not verify live provider behavior or the real model's tool-selection quality.
