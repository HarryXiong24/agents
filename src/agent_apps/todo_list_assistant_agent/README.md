# Todo List Assistant Agent

English | [简体中文](README.zh-CN.md)

A console-based Todo List Assistant Agent built with LangGraph. It combines five local
tools, three graph nodes, rolling conversation summaries, SQLite checkpoints,
SQLite todo storage, and a custom State reducer retaining the recent tool
execution records. Each todo has exactly three fields: `project` (name), `minutes`
(estimated duration), and `date` (scheduled date).

Code comments, tool descriptions, prompts, and terminal messages are in English.
The assistant replies in English by default and can use another language when
explicitly requested. This README describes current usage and design; the
[Learning Guide](docs/VERSIONS.md) records the learning roadmap and changes.

| Tool | Purpose |
|---|---|
| `get_current_time` | Read the computer's local date and time |
| `calculate` | Add, subtract, multiply, or divide numbers |
| `save_todo` | Add a todo or update its estimated duration for the same name/date |
| `delete_todo` | Delete the todo matching a name and scheduled date |
| `get_tool_history` | Read the current conversation's retained recent tool executions |

## Todo fields and storage

Todos persist across restarts and are shared by conversations in this application. Each conversation separately stores its messages, summary, and tool execution records.

| Stored field | Todo meaning |
|---|---|
| `project` | Todo name |
| `minutes` | Estimated duration, an integer from 1 to 1440 |
| `date` | Scheduled date in `YYYY-MM-DD` format |

All three fields are required when saving. There is no completion/status field: saying a todo is done does not delete it or mark it complete. Updating the same name and date changes only duration; changing a name or date adds another record, rather than replacing the old one.

Todo records use `data/todos.sqlite`, the `todos` table, and the `TodoItem` type. Storage functions are `load_todos()`, `save_todo()`, and `delete_todo()` in `agent/memory.py`; the model-facing tools are `save_todo` and `delete_todo` in `agent/tools.py`. Conversations and summaries use `data/todo_checkpoints.sqlite`.

## Run

Keep model settings in this agent's own `src/agent_apps/todo_list_assistant_agent/.env`, at the application root beside the `config/` package. If the file is missing, copy the adjacent [`.env.example`](.env.example) to `.env` and fill in your API key:

```dotenv
GROQ_API_KEY=your-api-key
AGENT_MODEL=openai/gpt-oss-20b
GROQ_BASE_URL=https://api.groq.com
```

From the repository root:

```bash
uv run todo-list-assistant-agent
```

Every launch opens a conversation menu:

```text
Conversations
1. home-todos
2. work-todos
0. New conversation
Type 'exit' to quit.
Choose a conversation:
```

Choose an existing conversation by number, or enter `0` and name a new conversation. A new conversation is saved after its first message; exiting before sending anything does not create a saved entry. The first launch shows an empty list. Menu browsing and quitting need no API key.

With the project's installed virtual environment activated, you can also run:

```bash
python -m agent_apps.todo_list_assistant_agent
```

The module entry point opens the same menu. Names serve as internal `thread_id` values and are case-sensitive. Surrounding whitespace is removed; empty or existing names are rejected when creating a conversation. Conversations saved in the checkpoint database remain selectable after restart. There is no automatic default selection or command-line conversation option.

Type `exit` or `quit`, or press Ctrl+C, to stop. Exit commands are case-insensitive. Configuration is read only from the agent-local `.env`, independently of the working directory. The outer repository `.env` and same-named shell variables are not used. Values are read without modifying `os.environ` or expanding `${...}` references. The private `.env` is ignored by Git; `.env.example` is the shareable template.

The console uses Python's standard `readline` module for Unicode editing and backspace without automatically recording input history. The current environment is macOS; no extra terminal package is required.

## Try three conversations

Ordinary conversation needs no tool:

```text
You: Hello, help me organize my errands.
Assistant: ...
```

Arithmetic can require more than one tool call:

```text
You: If I have seven tasks taking 45 minutes each, how many hours is that? Calculate step by step.
Tool: Calculating 45.0 multiply 7.0.
Tool: Calculating 315.0 divide 60.0.
Assistant: That is 315 minutes, or 5.25 hours.
```

This is an illustrative trace. Actual wording and tool-call order depend on the model. Calculator operations are `add`, `subtract`, `multiply`, and `divide`.

Conversation history lets the model reuse information from an earlier turn:

```text
You: I have 30 minutes available for chores each day.
Assistant: ...
You: Using that daily time, how many hours are available in a week?
Assistant: ...
```

Ask "What time is it?" to observe the time tool. It returns local time in `YYYY-MM-DD HH:MM:SS` format.

## Read one block at a time

1. `agent/tools.py`: how `@tool`, parameter types, and descriptions expose local functions to the model.
2. `config/` and `agent/model.py`: configuration loading and validation, followed by model creation.
3. `agent/memory.py` and `agent/prompts.py`: how todos are stored, queried, and inserted into the system prompt.
4. `agent/state.py` and `agent/graph.py`: how `call_tools()` returns new records and the reducer merges them. Then read `agent/summarization.py` for the summary node before the model/tool loop.
5. `agent/checkpoints.py` and `console.py`: how storage returns a list of conversation names, the menu selects one, and `chat()` sends new messages with its `thread_id`.
6. `main()` and `__main__.py`: how the application starts and keeps `SqliteSaver` open.

The core loop is:

```text
User input -> Summary check -> Model node
                |-- Tool calls -> Tool node -> Model node
                |-- Final answer -> End turn -> Wait for user input
```

`bind_tools()` exposes names, parameters, and descriptions. The model returns a request; `ToolNode` actually executes it and sends tool-result messages back to the model.

Models do not always follow instructions perfectly. Check the printed tool messages to see what actually executed. The program does not display the model's private reasoning.

## Persistent conversations

Start `uv run todo-list-assistant-agent`, choose `0`, name the conversation `home-todos`, say "I want to organize my errands," then exit. Start again, select `home-todos` by its displayed number, and ask "What did I want to organize?" The graph restores messages from `data/todo_checkpoints.sqlite` using that conversation's `thread_id`.

Create another conversation named `work-todos` for separate history. Startup always asks you to choose; you do not need to remember or pass an ID. Displayed numbers are temporary menu positions, while the saved conversation names remain stable.

The console sends only the new `HumanMessage`. `AgentState` extends `MessagesState` with optional `summary` and `tool_history` fields. The checkpointer saves them together with recent user messages, model replies, tool requests, and tool results.

## Rolling conversation summaries

Before the first model call of each new user turn, the summary node estimates tokens in the existing summary and message history. At or above the configured threshold, it combines the old summary with older completed turns, keeping the latest **two completed user turns plus the current turn** in their original form. A turn includes all of its tool requests, results, and final answer; it is not a single message.

Edit `AgentConfig` in `config/agent.py` and restart. Agent settings are defined
in Python; `.env` contains only model settings. All four values should be positive integers:

```python
@dataclass(frozen=True)
class AgentConfig:
    summary_trigger_tokens: int = 500
    summary_keep_turns: int = 2
    recursion_limit: int = 20
    tool_history_limit: int = 10
```

For a lower summary threshold, change `summary_trigger_tokens` to `300`;
for less frequent compression, try `6000`. `summary_keep_turns` controls how many
completed turns remain verbatim. `recursion_limit` bounds graph steps per invocation,
including summary/model/tool nodes; it is not a separate tool-call count.
`tool_history_limit` controls retained execution records per conversation.
These settings are developer-maintained defaults without runtime constructor validation.

The threshold counts only the summary and conversation messages, excluding fixed system instructions, saved todos, and tool definitions. It uses LangChain's approximate character-based counter, not Groq's exact tokenizer. Four or five sufficiently detailed turns may trigger compression at 500, but very short exchanges can take longer. Lowering the threshold still cannot compress until there are older turns beyond the two retained turns.

For a quick test, create a conversation and discuss household chores, work tasks, available time, and scheduling preferences in four successive messages. Ask for reasonably detailed replies. After compression, a successful turn prints:

```text
Context: Earlier conversation summarized; recent turns kept.
```

The base model generates the summary without tool binding. Its Markdown instructions target roughly **100-150 tokens**, preserving goals, constraints, corrections, decisions, and open questions. This is a soft target. If a valid summary is not shorter than the older context, compression is skipped and the agent answers using the unchanged history and previous summary. Empty, truncated, or tool-calling summaries remain errors, preserving original state for recovery. Summary generation attempts add API usage and latency even if compression is skipped, but do not become normal assistant messages.

The response model receives system instructions, the latest database todo list, the historical summary, and recent original messages. The summary is historical data, not new instructions; current saved todos remain authoritative. No summary operation saves or deletes todos.

Compression updates the current graph state using `RemoveMessage`. Older checkpoint snapshots remain in SQLite, so the database file does not automatically shrink. Restarting the same conversation restores its summary and recent messages. Long individual inputs, large retained turns, or very large old histories can still exceed a model's capacity; the application does not implement chunked summarization or a hard context limit.

## State and tool execution history

`ToolCallRecord` describes each execution. The optional `tool_history` field uses the custom
`add_tool_history(old, new)` reducer, which reads the shared `AGENT_CONFIG`. `messages` merges by message ID, `summary`
is replaced when updated, and `tool_history` concatenates updates while retaining
the configured number of recent entries (ten by default). Nodes return only their new values; LangGraph applies each
field's merge rule.

The `call_tools()` node also returns new `tool_history` records containing each tool's
name, requested arguments, actual result text, and a timestamp with the local UTC
offset. `add_tool_history()` merges them with previous records and retains the configured
number of recent entries (ten by default) per conversation. These records are checkpointed, survive summary compression,
and are available in `graph.get_state(config).values.get("tool_history", [])`.
They are not automatically added to every model prompt. The read-only `get_tool_history` tool reads the current conversation's records through injected `ToolRuntime.state` and returns them to the model on demand. The lookup itself is excluded from tool history, so querying does not consume a record slot or nest history inside its own output.

Ask "Which tools ran in this conversation? Show the arguments, results, and timestamps." The assistant should call `get_tool_history` and present retained recent executions (up to ten by default). An empty list means there are no records to show. The lookup takes no model-supplied arguments and reads the state before its tool batch; to include another tool's new execution, query in a subsequent step. There is no separate console command or automatic history panel.

The graph has three nodes and five tools. Tool history uses the existing
checkpoint database and has no separate table; retention is configured by
`AgentConfig.tool_history_limit`.
`call_tools()` wraps `ToolNode` to generate the records. The graph uses
`recursion_limit=20` by default; it has no separate per-tool execution budget or middleware-based
recording.

Reducing `tool_history_limit` applies when the next tool-node update is merged.
Restoring a checkpoint does not itself run reducers, so saved records can exceed
a newly reduced limit until then; a first history lookup can return that older list.

## SQLite todo storage

```text
You: Add a todo to clean my room on 2026-11-04, estimated at 30 minutes.
Tool: Saved todo: Clean room, estimated 30 minutes, scheduled for 2026-11-04.
Assistant: ...
You: exit
```

Restart and ask "What todos do I have?" Before every model call, the program queries all todos from `data/todos.sqlite` and adds them to the system prompt.

The `todos` table has only `project`, `minutes`, and `date` business fields. Todo name (`project`) and scheduled date form a composite primary key. Queries still return the same dictionary-list structure for prompt formatting:

```json
[
  {"project": "Clean room", "minutes": 30, "date": "2026-11-04"},
  {"project": "Review pull request", "minutes": 45, "date": "2026-11-04"}
]
```

Estimated duration must be an integer from 1 to 1440 minutes, and the date must be a real calendar date in `YYYY-MM-DD` format. The assistant should ask for any missing field, use the time tool to resolve relative dates, and convert hours to minutes.

Saving the same name and date updates estimated duration. A different name or date adds a todo while preserving others. Ordinary conversation and temporary calculations do not automatically write todos. For example, "Update the Clean room todo on 2026-11-04 to 45 minutes" changes only that todo.

The first query or write creates the database. Its path comes from `config.DATA_DIR` and is excluded from Git. Python's built-in `sqlite3` needs no database server. Each operation opens its own connection, commits or rolls back, and closes it.

## Storage initialization

The application creates missing database files and tables on first use. Without existing data, the todo list and conversation menu start empty. Later restarts reuse the saved todos, conversations, summaries, and tool history. Both database paths are anchored to the application directory and excluded from Git.

## Delete a todo

```text
You: Delete the Clean room todo for 2026-11-04.
Tool: Deleted todo: Clean room, 2026-11-04.
Assistant: ...
```

Deletion matches the todo name (`project`) and scheduled date, without requiring estimated duration. The assistant should ask if the target is unclear. A missing todo returns "No todos were deleted." Other names and dates remain intact. Deleting the last todo leaves an empty table, and queries return `[]`, including after restart.

## Project layout and prompts

```text
todo_list_assistant_agent/
├── AGENTS.md                     # Coding-agent instructions
├── CLAUDE.md                     # Identical instructions, English then Chinese
├── .env                          # Private local configuration; ignored by Git
├── .env.example                  # Shareable configuration template
├── __init__.py
├── __main__.py                   # Python module entry point
├── main.py                       # Resource lifetime and application composition
├── console.py                    # Conversation menu, input/output, and errors
├── config/
│   ├── __init__.py                # Public exports only
│   ├── agent.py                   # Agent summary and execution settings
│   ├── model.py                   # Model settings, defaults, and validation
│   └── app.py                     # Paths, .env reading, and AppConfig assembly
├── agent/
│   ├── __init__.py
│   ├── graph.py                  # Summary, model, and tool nodes
│   ├── state.py                  # Messages, summary, and tool-history reducer
│   ├── tools.py                  # Time, arithmetic, todos, and history lookup
│   ├── model.py                  # Chat model creation
│   ├── prompts.py                # Template loading and dynamic prompt formatting
│   ├── summarization.py          # Token estimate and summary updates
│   ├── memory.py                 # Todo validation and SQLite CRUD
│   ├── checkpoints.py            # Checkpoint paths and conversation queries
│   └── prompt_templates/         # Markdown only; no __init__.py
│       ├── system_prompt.md
│       ├── todo_list_prompt.md
│       └── summary_prompt.md
├── data/                         # Personal SQLite files; ignored by Git
├── docs/                         # Bilingual learning guides
└── tests/                        # Offline tests with temporary storage
```

The application uses these responsibility boundaries:

| Layer | Location | Responsibility |
|---|---|---|
| Entry and interaction | `main.py`, `console.py` | Resource lifetime, composition, session menu, and input/output |
| Agent execution | `agent/graph.py`, `state.py`, `tools.py`, and related modules | Graph, State, tools, model, prompts, and summarization |
| Agent persistence | `agent/memory.py`, `agent/checkpoints.py` | Todo SQLite CRUD and checkpoint conversation queries |
| Shared configuration | `config/` | Central settings loading, defaults, validation, and application data paths |

`main.py` assembles the parts. The `agent/` package includes execution logic and
its persistence helpers; those helpers depend on configuration rather than terminal
interaction. `.env` and `data/` stay at the application root. `config.DATA_DIR`
anchors both SQLite files, independently of module locations.

Edit the relevant `.md` file under `agent/prompt_templates/` to change instructions. `agent/prompts.py` loads templates as UTF-8 and formats todo data. Templates load at import time, so restart after editing. The short tool-error instruction remains the `TOOL_ERROR_MESSAGE` string in `agent/prompts.py`.

Filenames use lowercase and Python constants use uppercase; their casing does not need to match. `agent/graph.py` imports prompt helpers through `from .prompts import ...`; `main.py` imports `build_graph()` through `from .agent.graph import build_graph`.

`main.py` opens the saver, gets `threads = checkpoints.list_threads(checkpointer)`, and passes that ordinary list to `select_thread(threads)` in `console.py`. The menu does not access the database. `agent/checkpoints.py` owns `CHECKPOINTS_FILE` and the SQL used to list saved conversations; `console.py` owns `select_thread()` and `chat()`. Startup enters the conversation menu directly, without command-line argument parsing.

`config/` has three responsibility modules. `agent.py` defines `AgentConfig`:
summary settings, graph execution steps, and tool history retention. `model.py`
defines and parses `ModelConfig`. `app.py` owns paths, `AppConfig`, the single
`read_env()` function, and `load_config()` assembly. Only model settings are read
from `.env`; `config/agent.py` creates one shared `AGENT_CONFIG = AgentConfig()` object.
`load_config()` exposes that same object as `settings.agent`; the graph and reducer
read it directly. All State fields stay together in `AgentState`.
`config/__init__.py` only re-exports public names. There is no separate Agent
configuration loader or environment parser.

After conversation selection, `main.py` calls `load_config()` once, passing
`settings.model` to `create_model()`. `build_graph()` and the State reducer use
the shared `config/agent.py` object.
`agent/model.py` only creates the client from supplied settings; it never reads
`.env` or supplies configuration defaults. Importing the configuration package
performs no file reads. Browsing the menu and exiting still require no API key.
Tests or other callers can pass an explicit path with `load_config(env_file)`
without changing the application's default file location.

## Two kinds of memory

`data/todo_checkpoints.sqlite` stores graph state by `thread_id`, including conversation history and execution progress. `data/todos.sqlite` stores the three-field todos. Different threads have separate conversations but share the same todo list; a thread ID is not a user account.

Both files survive restart and are excluded from Git. The latest graph state keeps recent original messages, a lossy historical summary, and recent tool execution records per conversation (up to ten by default). Choose `0` at startup for a fresh conversation. Run one console at a time for a given conversation.

Expected graph/API/storage errors end the console session and preserve whatever checkpoints were successfully saved. On restart, `get_state(config).next` detects unfinished work and `invoke(None, config)` continues it before new input is accepted. Completed checkpointed steps are reused; a node interrupted before its result was saved may run again. Checkpoints and todo writes are separate transactions, so this is not an exactly-once guarantee for tool side effects. A later model failure does not roll back a committed todo change.

The calculator uses floating-point arithmetic for everyday duration calculations, rather than exact financial accounting.

## Further reading

Follow `call_tools()` in `agent/graph.py` to see how tool results become State updates,
then `add_tool_history()` in `agent/state.py` to see how records are merged. Read
`agent/summarization.py` for token thresholds, complete-turn retention, and `RemoveMessage`.
The [Learning Guide](docs/VERSIONS.md) provides diagrams, reading order, and exercises.

## Offline checks

From the repository root:

```bash
uv run pytest -q src/agent_apps/todo_list_assistant_agent/tests
```

Tests use simulated models, temporary configuration files, and temporary databases without real API keys or network. They cover configuration isolation, threshold boundaries, rolling summaries, tool-pair preservation, failed summary recovery, cross-process restoration, pending todo tool recovery, bounded tool history, read-only history queries, runtime injection, summary preservation of tool records, todo CRUD, and Unicode input and storage.
