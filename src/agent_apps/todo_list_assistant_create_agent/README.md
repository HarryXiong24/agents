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
- “Plan my Python study for tomorrow, 2 hours total.” — may load the `study-plan` skill.
- “Clean up my todo list.” — may load the read-only `todo-cleanup` skill.
- “Split Python's 70 minutes into pomodoros.” — calls the example MCP server when configured.

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
| Skills | Local `SKILL.md` playbooks; catalog always visible, instructions loaded on request |
| MCP tools | Servers from local `mcp.json` (stdio or streamable HTTP); approval on by default |
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

## Skills

Skills follow the Agent Skills layout: one directory per skill under `skills/`,
each with a `SKILL.md` that starts with YAML frontmatter.

```text
skills/
├── study-plan/
│   ├── SKILL.md
│   └── references/session-guide.md
└── todo-cleanup/
    └── SKILL.md
```

```markdown
---
name: study-plan            # lowercase/digits/hyphens; must equal the directory
description: What it does and when to use it (1–1024 characters).
---

# Markdown instructions for the main model
```

Skills are disclosed progressively:

| Level | When | Content | Mechanism |
|---|---|---|---|
| 1. Catalog | Every main-model call | Name and description of every skill | `SkillsMiddleware.wrap_model_call` |
| 2. Instructions | After `load_skill(name)` | The `SKILL.md` body | Name stored in `active_skills`, body injected on later calls |
| 3. References | `read_skill_file(name, path)` | A `references/*.md` or `*.txt` file | Returned as a tool result |

- Skills are loaded once at startup. A malformed skill (frontmatter, name, size,
  UTF-8, or a reference that resolves outside its directory) stops startup with
  `Startup failed: ...` rather than being skipped. Edit files and restart to apply.
- State stores only skill names. Instructions live in the system message, not in
  `messages`, so summarization does not remove them. They persist per conversation
  until newer loads push them past `max_active_skills`.
- `read_skill_file` is enforced to work only for an active skill and a preloaded
  path; it never touches the disk at call time. Scripts and assets are not loaded
  or executed.
- `load_skill` and `read_skill_file` are ordinary tools: each uses one tool slot and
  one model step, appears in tool history and follows the one-call rule.
- Skills are prompt guidance from trusted, version-controlled files. They cannot
  bypass approval, validation or quotas. Without a `skills/` directory, neither
  skill tool nor the Skills prompt section is registered.

To add a skill, create `skills/<name>/SKILL.md`, optionally add `references/`,
then restart. Write only reviewed instructions: skill text enters the system prompt.

## MCP servers

Copy the example to enable the bundled, side-effect-free pomodoro server:

```bash
cp src/agent_apps/todo_list_assistant_create_agent/mcp.example.json src/agent_apps/todo_list_assistant_create_agent/mcp.json
```

```json
{
  "mcpServers": {
    "pomodoro": {
      "transport": "stdio",
      "command": "python",
      "args": ["-m", "agent_apps.todo_list_assistant_create_agent.mcp_servers.pomodoro"],
      "require_approval": false
    },
    "remote": {
      "transport": "streamable_http",
      "url": "https://example.test/mcp",
      "headers": {"Authorization": "Bearer ${MCP_TOKEN}"},
      "tools": ["search"],
      "timeout": 30
    }
  }
}
```

| Field | Meaning |
|---|---|
| `transport` | `stdio` (default) or `streamable_http` |
| `command` / `args` / `env` / `cwd` | stdio process; the literal command `python` is the interpreter running this app |
| `url` / `headers` | streamable HTTP endpoint |
| `tools` | Optional allowlist of the server's tool names; omitted means all |
| `require_approval` | Default `true`: built-in HITL pauses every tool of this server |
| `timeout` | Seconds for the handshake and for each call (default 30, max 600) |

- `${NAME}` placeholders resolve only from this application's `.env`; a missing
  value stops startup. Values taken from `.env` are not expanded a second time,
  so literal `$` and `${NAME}` inside them stay unchanged. Shell variables are
  not used for substitution. `mcp.json` is Git-ignored.
- stdio servers receive the MCP SDK's safe default environment (such as `PATH`
  and `HOME`) plus their own `env`, not the full shell environment.
- Servers connect once after the conversation menu and stay open until exit.
  Startup prints `MCP tools: ...`. A server that cannot start, list its tools
  within `timeout`, or satisfy its allowlist stops startup.
- On exit, sessions receive 10 seconds to close normally. If cleanup is still
  pending, the owning task is cancelled and awaited; remaining tasks are also
  cancelled and awaited before the event loop is closed. Cancellation cleanup
  may take additional time, so 10 seconds is not a hard total shutdown deadline.
- Each tool is exposed as `<server>_<tool>`, described as `[MCP server: name]`.
  Names must be provider-safe and unique among all tools, or startup stops.
- MCP tools are ordinary tools here: one per model step, counted in the tool
  quota before approval, recorded in tool history and logged with timing.
- A server-reported error (`isError`) becomes an error ToolMessage the model can
  read. Timeouts and transport/session failures raise `McpServerError`; the
  console reports it and ends the turn. There is no reconnection or retry loop.
- Results are flattened to text; non-text content is named but not forwarded.
  The prompt tells the model to treat MCP results as data, not instructions;
  that is guidance, while approval and quotas are enforced by code.

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
| `max_active_skills` | `config/agent.py` | 2 most recently loaded skills |
| `SKILLS_DIR` | `config/app.py` | `skills/` in this application |
| `MCP_FILE` | `config/app.py` | `mcp.json` in this application; absent means no MCP |

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
mcp.json
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
config/                      app.py, model.py, agent.py, mcp.py
agent/agent.py               create_agent and middleware composition
agent/middleware/            One module per middleware responsibility
agent/state.py               Custom fields and bounded history reducer
agent/tools/                 Tools grouped by capability; __init__.py assembles them
agent/skills.py              SKILL.md loading and validation
skills/                      Shipped skill directories
agent/mcp.py                 MCP sessions on a background loop; sync tool wrappers
mcp_servers/                 Example stdio MCP server (pomodoro)
mcp.example.json             Example MCP configuration to copy to mcp.json
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
├── skills.py
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
├── draft.py
└── skills.py
```

`tools/__init__.py` defines `create_tools(model, skills)`, which remains available through
`from .tools import create_tools`. Skill tools are appended only when skills exist. Save/delete/list stay together in `todos.py`;
`draft.py` contains the model-bound draft tool, `DraftGenerator` and business
validation. `schemas.py` defines the Pydantic request/output models. Graph runtime
injection supplies `ToolRuntime`; the model never provides it.

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
CRUD validation, skills, MCP (real local stdio servers, literal env values,
slow shutdown/startup cleanup and mocked HTTP session creation), SDK retries, local
configuration and terminal editing. They do
not verify live provider behavior or the real model's tool-selection quality.
