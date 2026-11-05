# Todo List Assistant

English | [简体中文](README.zh-CN.md)

A small agent for learning one building block at a time. The current version is **version 5**: a plain console, four local tools, three graph nodes, rolling conversation summaries, SQLite checkpoints, and SQLite todos. Each todo has exactly three fields: `project` (name), `minutes` (estimated duration), and `date` (scheduled date).

Code comments, tool descriptions, prompts, and terminal messages are in English. The assistant replies in English by default and can use another language when explicitly requested.

See [Version Learning Guide](docs/VERSIONS.md) for each version's learning goals, architecture diagram, changes, reading order, and exercises. Version 5 adds summary compression to version 4's persistent conversations. Todo CRUD stays unchanged; old JSON data is never imported.

## Todo fields and storage

This is a Todo naming and storage adjustment within version 5, before version 6. Todo records and conversations start in new database files; previous data is not imported or migrated.

| Stored field | Todo meaning |
|---|---|
| `project` | Todo name |
| `minutes` | Estimated duration, an integer from 1 to 1440 |
| `date` | Scheduled date in `YYYY-MM-DD` format |

All three fields are required when saving. This version has no completion/status field: saying a todo is done does not delete it or mark it complete. Updating the same name and date changes only duration; changing a name or date adds another record, rather than replacing the old one.

Todo records use `data/todos.sqlite`, the `todos` table, and the `TodoItem` type. Storage functions are `load_todos()`, `save_todo()`, and `delete_todo()` in `memory.py`; the model-facing tools are `save_todo` and `delete_todo` in `tools.py`. Conversations and summaries use `data/todo_checkpoints.sqlite`. Old tool aliases are removed. The package and `simple-react-agent` launch command keep their generic names.

## Run

Keep all four settings in this agent's own `src/agent_apps/simple_react_agent/.env`, beside `config.py`. If the file is missing, copy the adjacent [`.env.example`](.env.example) to `.env` and fill in your API key:

```dotenv
GROQ_API_KEY=your-api-key
AGENT_MODEL=openai/gpt-oss-20b
GROQ_BASE_URL=https://api.groq.com
SUMMARY_TRIGGER_TOKENS=500
```

From the repository root:

```bash
uv run simple-react-agent
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
python -m agent_apps.simple_react_agent
```

The module entry point opens the same menu. Names serve as internal `thread_id` values and are case-sensitive. Surrounding whitespace is removed; empty or existing names are rejected when creating a conversation. Conversations saved in the new todo checkpoint database remain selectable after restart. There is no automatic default selection or command-line conversation option.

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

1. `tools.py`: how `@tool`, parameter types, and descriptions expose local functions to the model.
2. `config.py` and `model.py`: configuration loading and validation, followed by model creation.
3. `memory.py` and `prompts.py`: how todos are stored, queried, and inserted into the system prompt.
4. `state.py`, `summarization.py`, and `graph.py`: how the summary node prepares context before the model/tool loop.
5. `checkpoints.py` and `console.py`: how storage returns a list of conversation names, the menu selects one, and `chat()` sends new messages with its `thread_id`.
6. `main()` and `__main__.py`: how the application starts and keeps `SqliteSaver` open.

The core loop is:

```text
User input -> Summary check -> Model node
                |-- Tool calls -> Tool node -> Model node
                |-- Final answer -> End turn -> Wait for user input
```

`bind_tools()` exposes names, parameters, and descriptions. The model returns a request; `ToolNode` actually executes it and sends tool-result messages back to the model.

Models do not always follow instructions perfectly. Check the printed tool messages to see what actually executed. The program does not display the model's private reasoning.

## Persistent conversations (introduced in version 4)

Start `uv run simple-react-agent`, choose `0`, name the conversation `home-todos`, say "I want to organize my errands," then exit. Start again, select `home-todos` by its displayed number, and ask "What did I want to organize?" The graph restores messages from `data/todo_checkpoints.sqlite` using that conversation's `thread_id`.

Create another conversation named `work-todos` for separate history. Startup always asks you to choose; you do not need to remember or pass an ID. Displayed numbers are temporary menu positions, while the saved conversation names remain stable.

The console sends only the new `HumanMessage`. `AgentState` extends `MessagesState` with an optional `summary`. The checkpointer saves that summary together with recent user messages, model replies, tool requests, and tool results.

## Version 5: rolling conversation summaries

Before the first model call of each new user turn, the summary node estimates tokens in the existing summary and message history. At or above the configured threshold, it combines the old summary with older completed turns, keeping the latest **two completed user turns plus the current turn** in their original form. A turn includes all of its tool requests, results, and final answer; it is not a single message.

Set `SUMMARY_TRIGGER_TOKENS` in `src/agent_apps/simple_react_agent/.env`. The default is **500** when the setting is absent; an explicit value must be a positive integer. Restart after changing it. For example:

```dotenv
# Easy-to-observe learning default; use a larger value such as 6000 later.
SUMMARY_TRIGGER_TOKENS=500
```

To test a lower threshold, change the value in this same local file to `300` and restart. Exporting a global variable does not override this agent's file.

The threshold counts only the summary and conversation messages, excluding fixed system instructions, saved todos, and tool definitions. It uses LangChain's approximate character-based counter, not Groq's exact tokenizer. Four or five sufficiently detailed turns may trigger compression at 500, but very short exchanges can take longer. Lowering the threshold still cannot compress until there are older turns beyond the two retained turns.

For a quick test, create a conversation and discuss household chores, work tasks, available time, and scheduling preferences in four successive messages. Ask for reasonably detailed replies. After compression, a successful turn prints:

```text
Context: Earlier conversation summarized; recent turns kept.
```

The base model generates the summary without tool binding. Its Markdown instructions target roughly **100-150 tokens**, preserving goals, constraints, corrections, decisions, and open questions. This is a soft target. If a valid summary is not shorter than the older context, compression is skipped and the agent answers using the unchanged history and previous summary. Empty, truncated, or tool-calling summaries remain errors, preserving original state for recovery. Summary generation attempts add API usage and latency even if compression is skipped, but do not become normal assistant messages.

The response model receives system instructions, the latest database todo list, the historical summary, and recent original messages. The summary is historical data, not new instructions; current saved todos remain authoritative. No summary operation saves or deletes todos.

Compression updates the current graph state using `RemoveMessage`. Older checkpoint snapshots remain in SQLite, so the database file does not automatically shrink. Restarting the same conversation restores its summary and recent messages. Long individual inputs, large retained turns, or very large old histories can still exceed a model's capacity; this version does not implement chunked summarization or a hard context limit.

## SQLite todos (introduced in version 3)

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

The first query or write creates the database. Its path is anchored to `memory.py` and excluded from Git. Python's built-in `sqlite3` needs no database server. Each operation opens its own connection, commits or rolls back, and closes it.

## Storage initialization

The application creates the new databases on first use. The first launch has an empty todo list and conversation menu. Old `data/study_plans.sqlite`, `data/checkpoints.sqlite`, and JSON files are ignored and are not migrated or automatically deleted. You can delete those old files yourself. Later restarts reuse the new todo records, conversations, and summaries.

## Delete a todo

```text
You: Delete the Clean room todo for 2026-11-04.
Tool: Deleted todo: Clean room, 2026-11-04.
Assistant: ...
```

Deletion matches the todo name (`project`) and scheduled date, without requiring estimated duration. The assistant should ask if the target is unclear. A missing todo returns "No todos were deleted." Other names and dates remain intact. Deleting the last todo leaves an empty table, and queries return `[]`, including after restart.

## Markdown prompts

```text
simple_react_agent/
├── .env                          # Private local configuration; ignored by Git
├── .env.example                  # Shareable configuration template
├── main.py                       # Startup, resource lifetime, and composition
├── checkpoints.py               # Checkpoint path and saved conversation queries
├── console.py                   # Menu, chat, and terminal error messages
├── config.py                     # Local .env loading, parsing, and validation
├── state.py                      # Recent messages and historical summary
├── summarization.py              # Token estimate, safe turn selection, summary update
├── graph.py                      # Summary, model, and tool nodes
├── prompts.py                    # Load templates and insert todo data
└── prompt_templates/            # Markdown only; no __init__.py
    ├── system_prompt.md          # Role, tools, saving, and deletion rules
    ├── todo_list_prompt.md       # Todo-list template with the {todos} placeholder
    └── summary_prompt.md         # Rolling-summary instructions, no tools
```

Edit the relevant `.md` file to change instructions. `prompts.py` loads templates as UTF-8 and formats todo data. Templates load at import time, so restart after editing. The short tool-error instruction remains the `TOOL_ERROR_MESSAGE` string in `prompts.py`.

Filenames use lowercase and Python constants use uppercase; their casing does not need to match. `graph.py` imports prompt helpers through `from .prompts import ...`; `main.py` imports `build_graph()` from `graph.py`.

`main.py` opens the saver, gets `threads = checkpoints.list_threads(checkpointer)`, and passes that ordinary list to `select_thread(threads)` in `console.py`. The menu does not access the database. `checkpoints.py` owns `CHECKPOINTS_FILE` and the SQL used to list saved conversations; `console.py` owns `select_thread()` and `chat()`. Startup enters the conversation menu directly, without command-line argument parsing.

`config.py` owns `ENV_FILE`, `read_env()`, `SummaryConfig`, and configuration parsing/validation. File reading is part of configuration loading and stays in the same module. `model.py` uses `config.read_env()` to create the model; `main.py` assembles the application.

## Two kinds of memory

`data/todo_checkpoints.sqlite` stores graph state by `thread_id`, including conversation history and execution progress. `data/todos.sqlite` stores the three-field todos. Different threads have separate conversations but share the same todo list; a thread ID is not a user account.

Both files survive restart and are excluded from Git. Version 5 keeps recent original messages and a lossy historical summary in the latest graph state. Choose `0` at startup for a fresh conversation. Run one console at a time for a given conversation.

Expected graph/API/storage errors end the console session and preserve whatever checkpoints were successfully saved. On restart, `get_state(config).next` detects unfinished work and `invoke(None, config)` continues it before new input is accepted. Completed checkpointed steps are reused; a node interrupted before its result was saved may run again. Checkpoints and todo writes are separate transactions, so this is not an exactly-once guarantee for tool side effects. A later model failure does not roll back a committed todo change.

The calculator uses floating-point arithmetic for everyday duration calculations, rather than exact financial accounting.

## Next exercise

Add a local "minutes to hours" tool to `TOOLS` and observe why the graph edges need no changes.

Use the [Version Learning Guide](docs/VERSIONS.md) to study summary state, token thresholds, complete turns, and `RemoveMessage`. Keep the current three stored fields while practicing the existing todo CRUD behavior.

## Offline checks

From the repository root:

```bash
uv run pytest -q src/agent_apps/simple_react_agent/tests
```

Tests use simulated models, temporary configuration files, and temporary databases without real API keys or network. They cover configuration isolation, threshold boundaries, rolling summaries, tool-pair preservation, failed summary recovery, cross-process restoration, pending todo tool recovery, todo CRUD, and Unicode input and storage.
