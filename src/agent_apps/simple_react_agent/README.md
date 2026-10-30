# Study Time Assistant

English | [简体中文](README.zh-CN.md)

A small agent for learning one building block at a time. The current version is **version 4**: a plain console, four local tools, two graph nodes, SQLite conversation checkpoints, and SQLite study plans. Each plan has exactly three fields: project, duration, and date.

Code comments, tool descriptions, prompts, and terminal messages are in English. The assistant replies in English by default and can use another language when explicitly requested.

See [Version Learning Guide](docs/VERSIONS.md) for each version's learning goals, architecture diagram, changes, reading order, and exercises. Version 4 adds persistent conversations while retaining the study-plan CRUD behavior. Old JSON data is never imported.

## Run

Set your API key in the repository root `.env`. Existing model settings can be reused:

```dotenv
GROQ_API_KEY=your-api-key
AGENT_MODEL=openai/gpt-oss-20b
GROQ_BASE_URL=https://api.groq.com
```

From the repository root:

```bash
uv run simple-react-agent
```

Every launch opens a conversation menu:

```text
Conversations
1. study-english
2. study-python
0. New conversation
Type 'exit' to quit.
Choose a conversation:
```

Choose an existing conversation by number, or enter `0` and name a new conversation. A new conversation is saved after its first message; exiting before sending anything does not create a saved entry. The first launch shows an empty list. Menu browsing and quitting need no API key.

With the project's installed virtual environment activated, you can also run:

```bash
python -m agent_apps.simple_react_agent
```

The module entry point opens the same menu. Names serve as internal `thread_id` values and are case-sensitive. Surrounding whitespace is removed; empty or existing names are rejected when creating a conversation. Older saved conversations, including `default`, remain selectable. There is no automatic default selection or command-line conversation option.

Type `exit` or `quit`, or press Ctrl+C, to stop. Exit commands are case-insensitive. Exported environment variables take precedence over `.env`.

The console uses Python's standard `readline` module for Unicode editing and backspace without automatically recording input history. The current environment is macOS; no extra terminal package is required.

## Try three conversations

Ordinary conversation needs no tool:

```text
You: Hello, I want to start learning Python.
Assistant: ...
```

Arithmetic can require more than one tool call:

```text
You: If I study 45 minutes a day for 7 days, how many hours is that? Calculate step by step.
Tool: Calculating 45.0 multiply 7.0.
Tool: Calculating 315.0 divide 60.0.
Assistant: That is 315 minutes, or 5.25 hours.
```

This is an illustrative trace. Actual wording and tool-call order depend on the model. Calculator operations are `add`, `subtract`, `multiply`, and `divide`.

Conversation history lets the model reuse information from an earlier turn:

```text
You: I only have 30 minutes a day to study.
Assistant: ...
You: Using the time I just mentioned, how many hours can I study in a week?
Assistant: ...
```

Ask "What time is it?" to observe the time tool. It returns local time in `YYYY-MM-DD HH:MM:SS` format.

## Read one block at a time

1. `tools.py`: how `@tool`, parameter types, and descriptions expose local functions to the model.
2. `model.py`: how `create_model()` reads configuration and creates the model.
3. `memory.py` and `prompts.py`: how plans are stored, queried, and inserted into the system prompt.
4. `graph.py` and `build_graph()`: how the model node, tool node, and conditional route form a loop.
5. `checkpoints.py` and `console.py`: how storage returns a list of conversation names, the menu selects one, and `chat()` sends new messages with its `thread_id`.
6. `main()` and `__main__.py`: how the application starts and keeps `SqliteSaver` open.

The core loop is:

```text
User input -> Model node
                |-- Tool calls -> Tool node -> Model node
                |-- Final answer -> End turn -> Wait for user input
```

`bind_tools()` exposes names, parameters, and descriptions. The model returns a request; `ToolNode` actually executes it and sends tool-result messages back to the model.

Models do not always follow instructions perfectly. Check the printed tool messages to see what actually executed. The program does not display the model's private reasoning.

## Version 4: persistent conversations

Start `uv run simple-react-agent`, choose `0`, name the conversation `study-python`, say "I want to learn decorators," then exit. Start again, select `study-python` by its displayed number, and ask "What did I want to learn?" The graph restores messages from `data/checkpoints.sqlite` using that conversation's `thread_id`.

Create another conversation named `study-english` for separate history. Startup always asks you to choose; you do not need to remember or pass an ID. Displayed numbers are temporary menu positions, while the saved conversation names remain stable.

The console sends only the new `HumanMessage`. `MessagesState` merges it with the restored state, and the checkpointer saves user messages, model replies, tool requests, and tool results. No extra graph nodes or tools are added.

## SQLite study plans (introduced in version 3)

```text
You: Save a study plan for Python on 2026-10-29, lasting 60 minutes.
Tool: Saved study plan: Python, 60 minutes, 2026-10-29.
Assistant: ...
You: exit
```

Restart and ask "What study plans do I have?" Before every model call, the program queries all plans from `data/study_plans.sqlite` and adds them to the system prompt.

The `study_plans` table has only `project`, `minutes`, and `date` business fields. Project and date form a composite primary key. Queries still return the same dictionary-list structure for prompt formatting:

```json
[
  {"project": "Python", "minutes": 60, "date": "2026-10-29"},
  {"project": "English", "minutes": 30, "date": "2026-10-29"}
]
```

Duration must be an integer from 1 to 1440 minutes, and the date must be a real calendar date in `YYYY-MM-DD` format. The assistant should ask for any missing field, use the time tool to resolve relative dates, and convert hours to minutes.

Saving the same project and date updates duration. A different project or date adds a plan while preserving others. Ordinary conversation and temporary calculations do not automatically write plans. For example, "Update the Python plan on 2026-10-29 to 90 minutes and save it" changes only that plan.

The first query or write creates the database. Its path is anchored to `memory.py` and excluded from Git. Python's built-in `sqlite3` needs no database server. Each operation opens its own connection, commits or rolls back, and closes it.

## Storage initialization

The plan database creates an empty table on first use. Old JSON is neither read nor imported. Existing SQLite plans remain unchanged when upgrading to version 4. The checkpoint database starts recording conversations from version 4; it cannot recover version 3's former in-memory chat history.

## Delete a plan

```text
You: Delete the Python study plan for 2026-10-29.
Tool: Deleted study plan: Python, 2026-10-29.
Assistant: ...
```

Deletion matches project and date, without requiring duration. The assistant should ask if the target is unclear. A missing plan returns "No plans were deleted." Other projects and dates remain intact. Deleting the last plan leaves an empty table, and queries return `[]`, including after restart.

## Markdown prompts

```text
simple_react_agent/
├── main.py                       # Startup, resource lifetime, and composition
├── checkpoints.py               # Checkpoint path and saved conversation queries
├── console.py                   # Menu, chat, and terminal error messages
├── graph.py                      # Graph construction, nodes, and routing
├── prompts.py                    # Load templates and insert plan data
└── prompt_templates/            # Markdown only; no __init__.py
    ├── system_prompt.md          # Role, tools, saving, and deletion rules
    └── study_plans_prompt.md     # Plan-list template with a {plans} placeholder
```

Edit the relevant `.md` file to change instructions. `prompts.py` loads templates as UTF-8 and formats plan data. Templates load at import time, so restart after editing. The short tool-error instruction remains the `TOOL_ERROR_MESSAGE` string in `prompts.py`.

Filenames use lowercase and Python constants use uppercase; their casing does not need to match. `graph.py` imports prompt helpers through `from .prompts import ...`; `main.py` imports `build_graph()` from `graph.py`.

`main.py` opens the saver, gets `threads = checkpoints.list_threads(checkpointer)`, and passes that ordinary list to `select_thread(threads)` in `console.py`. The menu does not access the database. `checkpoints.py` owns `CHECKPOINTS_FILE` and the SQL used to list saved conversations; `console.py` owns `select_thread()` and `chat()`. Startup enters the conversation menu directly, without command-line argument parsing.

## Two kinds of memory

`data/checkpoints.sqlite` stores graph state by `thread_id`, including conversation history and execution progress. `data/study_plans.sqlite` stores the three-field plans. Different threads have separate conversations but share the same plan list; a thread ID is not a user account.

Both files survive restart and are excluded from Git. History is not compacted yet; choose `0` at startup for a fresh conversation. Run one console at a time for a given conversation.

Expected graph/API/storage errors end the console session and preserve whatever checkpoints were successfully saved. On restart, `get_state(config).next` detects unfinished work and `invoke(None, config)` continues it before new input is accepted. Completed checkpointed steps are reused; a node interrupted before its result was saved may run again. Checkpoints and plan writes are separate transactions, so this is not an exactly-once guarantee for tool side effects. A later model failure does not roll back a committed plan change.

The calculator uses floating-point arithmetic for everyday duration calculations, rather than exact financial accounting.

## Next exercise

Add a local "minutes to hours" tool to `TOOLS` and observe why the graph edges need no changes.

Use the [Version Learning Guide](docs/VERSIONS.md) to study `SqliteSaver`, `thread_id`, state restoration, and the two kinds of memory. Keep the current three plan fields while practicing the existing CRUD behavior.

## Offline checks

From the repository root:

```bash
uv run pytest -q src/agent_apps/simple_react_agent/tests
```

Tests use a simulated model and temporary databases. They require no API key or network. Tests cover cross-process checkpoint restoration, conversation isolation, failure recovery, study-plan CRUD, and Unicode input and storage.
