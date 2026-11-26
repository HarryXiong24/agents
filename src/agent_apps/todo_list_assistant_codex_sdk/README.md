# Todo List Assistant · Codex SDK

[简体中文](README.zh-CN.md)

A terminal todo assistant built on the official Python Codex SDK. The [manual
LangGraph app](../todo_list_assistant_agent/README.md) and the
[`create_agent` app](../todo_list_assistant_create_agent/README.md) are alternative
implementations of the same assistant. Each app has its own conversations and todos.

From the repository root, install and launch:

```bash
uv sync --locked --extra codex-todo
uv run --locked --extra codex-todo todo-list-assistant-codex-sdk
```

The menu lists saved conversations. Enter `0` to name a new conversation, or
select a listed conversation to continue. Enter `exit` or `quit` to leave.
Listing conversations needs no model call. A new conversation appears in the
saved list once its first turn has started.

To authenticate, copy the app's [.env.example](.env.example) to `.env` in this
directory and set `OPENAI_API_KEY`, or sign in to the app's own Codex home with an
installed Codex CLI:

```bash
CODEX_HOME="$PWD/src/agent_apps/todo_list_assistant_codex_sdk/data/codex_home" codex login
```

Run the app once to create its local directories before the CLI login. A local
`OPENAI_API_KEY` signs the runtime in and can persist credentials in that home.
`CODEX_MODEL` is optional and applies to newly created conversations and drafts.
Resumed conversations use their saved model and provider. The Python package
installs its own compatible runtime. [Official Python SDK setup](https://github.com/openai/codex/blob/main/sdk/python/docs/getting-started.md)

| Try saying | Behavior |
|---|---|
| Save Python for 30 minutes on 2026-12-04. | Upserts `project`, `minutes`, and `date`. |
| List my todos on 2026-12-04. | Reads saved records with an optional exact date/name filter. |
| Change Python on 2026-12-04 to 45 minutes. | Updates the same project/date. |
| Delete Python on 2026-12-04. | The terminal previews the matching record and asks for `y` or `n`. |
| Propose Python and English on 2026-12-04 within 90 minutes. | Generates a validated, unsaved draft. |
| Save Python from the draft. | Reads the thread's current draft and saves the explicitly requested record. |
| Which tools ran? | Reads up to 10 recent results in this thread, including declined operations. |
| $study-plan Plan 90 minutes of Python for 2026-12-04. | Invokes the shipped skill through the SDK. |

Ordinary replies are free text. A draft uses a separate ephemeral Codex thread
with an output schema and Python validation for exact names, date, and total
duration. A new draft request replaces the previous candidate. Saving a todo
keeps the candidate available. The shipped `study-plan` and `todo-cleanup`
skills support explicit `$skill-name` input, and the agent can read their
reviewed instructions and allowed reference through a restricted tool.

`data/codex_home/` contains Codex history and authentication. `data/todos.sqlite`
stores todos shared across this app's conversations, plus thread-scoped drafts and
tool history. Pending approvals live only in the current console turn. If that
turn fails or the app exits, the remaining requests require a fresh request.
Already committed business changes remain saved. After a failed Codex turn,
restart the console and select the conversation to continue.

Copy [mcp.example.json](mcp.example.json) to `mcp.json` next to this README to
enable the bundled pomodoro server. Ask “Split 70 minutes into pomodoros.”
External servers can use `stdio` (`command`, `args`, `env`, `cwd`) or
`streamable_http` (`url`, `headers`). Use `tools` for an allowlist. `timeout`
defaults to 30 seconds. `require_approval` defaults to `true`. String values
support `${NAME}` substitution from the local `.env`. The literal command
`python` uses the interpreter running the app. Configure only servers you trust.

The app admits up to eight business tool requests per user turn and sets a
turn time limit in [config.py](config.py). Codex manages context compaction and
its internal inference loop. The application can cap business tools and interrupt
a timed out turn. It has no exact cap on the number of internal model calls.

Start with [main.py](main.py), then read [runtime.py](agent/runtime.py),
[gateway.py](agent/gateway.py), and [storage.py](agent/storage.py).
The [comparison guide](docs/COMPARISON.md) shows the execution and data flow.

```bash
uv run --locked --extra codex-todo pytest -q src/agent_apps/todo_list_assistant_codex_sdk/tests
TODO_TEST_CODEX_RUNTIME=1 uv run --locked --extra codex-todo pytest -q src/agent_apps/todo_list_assistant_codex_sdk/tests/test_runtime.py
```

The runtime check uses the installed Codex runtime, a loopback mock model, and
temporary storage. It does not require production credentials.
