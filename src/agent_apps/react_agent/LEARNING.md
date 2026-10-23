# Learning Guide

How to study this repo. The README explains *what* the architecture is; this guide is a
**reading path plus hands-on exercises** so you understand *why* each piece exists by
breaking and changing it yourself.

The code comments use four markers. Search for them (e.g. `grep -rn "📘" agent/`):

| Marker | Meaning |
|---|---|
| 📘 LEARN | The concept behind the code |
| ⚠ PITFALL | An easy mistake at this spot |
| 🔁 FLOW | Where execution goes next |
| 🧪 TRY | A small experiment to run |

---

## Reading order

Read in this order. Each step builds on the previous one.

| # | File | Focus on | Time |
|---|---|---|---|
| 1 | `agent/state.py` | State vs Context, reducers (`add_messages`: append / replace-by-id / remove) | 10 min |
| 2 | `agent/config.py` | Which numbers control the loop and memory | 5 min |
| 3 | `agent/tools.py` | Docstring = tool prompt, `ToolRuntime` injection, `interrupt()` inside a tool | 15 min |
| 4 | `mcp_servers/workspace_server.py` | MCP server side: FastMCP, sandboxing, stdout rule | 10 min |
| 5 | `agent/mcp_client.py` | MCP client side: how MCP tools become LangChain tools | 10 min |
| 6 | `agent/prompts.py` | Context engineering: the per-step system prompt | 10 min |
| 7 | `agent/memory.py` | The three memory layers, Store namespaces, recall strategies | 15 min |
| 8 | `agent/graph.py` ★ | Every node, the router, `interrupt()` re-execution, `Command` | 45 min |
| 9 | `main.py` | Streaming, the HITL driver loop, thread_id, slash commands | 20 min |
| 10 | `tests/test_graph.py` | How to test agent mechanics without a real model | 20 min |

---

## Core concepts, in one paragraph each

**ReAct.** The model alternates Reason (decide) and Act (call tool), reading each tool's
Observation before deciding again. With native function calling the loop is simply:
*while the model's reply has `tool_calls`, run them and call the model again.*
In the graph: `agent → tools → agent ...`, exit when `route_after_agent` sees no tool calls.

**Loop engineering.** An agent loop's exit is decided by a stochastic model, so you must
bound it from the outside. Five layers, soft to hard: budget awareness in the prompt →
forced final answer (no tools bound on the last step) → errors returned as observations →
loop guard steering → `recursion_limit` fuse. Plus an outer critic loop with its own cap.

**Human-in-the-loop.** `interrupt(payload)` saves a checkpoint and returns control to the
caller. The caller resumes with `Command(resume=value)` on the same `thread_id`; the
interrupted node re-runs from the top and `interrupt()` returns `value`. Two triggers here:
a policy (`approval_gate` for risky tool names) and the model itself (`ask_human` tool).

**MCP.** A protocol for serving tools from a separate process. Server publishes tool
schemas (`tools/list`) and executes calls (`tools/call`). The adapter wraps them as normal
LangChain tools, so to the model and the graph they are just more function-calling tools.

**Memory.** Short-term = thread messages persisted by the checkpointer. Compaction =
summarise + delete old messages when over budget. Long-term = Store namespaced by user,
recalled into the system prompt each turn and written by the model via tools.

**Context engineering.** The model only knows what is in its context window. The system
prompt is rebuilt every step from state, so it holds exactly the summary, memories,
warnings and budget that matter *now*.

---

## Exercises

Do them roughly in order. Each has a "what you should see" so you can check yourself.
Most need a Groq API key; the ones marked *(offline)* only need `pytest`.

### Level 1 — Observe

1. **Watch a ReAct loop.** Ask `what is 17% of 2380, plus 99?`
   *See:* `→ calculator(...)` and `← calculator: ...` lines, then the answer, then
   `✓ critic approved`. Run `/state`: `iterations=2` or `3`.

2. **Watch checkpoints.** After any turn run `/history`.
   *See:* one checkpoint per super-step; `next=` shows which node would run next.
   Count how many super-steps one tool call takes (compact → agent → tools → loop_guard).

3. **See the graph.** Run `/graph`, paste the output into <https://mermaid.live>.
   Match each box to a function in `graph.py`.

### Level 2 — Human-in-the-loop

4. **Approve, edit, reject.** Ask `create notes/today.md with a haiku about rain`.
   Try `[e]dit` and change the content; then check `cat workspace/notes/today.md`.
   Ask again and `[r]eject` with a reason. *See:* a red `← write_file: REJECTED ...` line
   and the model adapting its answer to your reason.

5. **Durable pause.** Ask for a file write. At the approval prompt, press Ctrl+C to quit.
   Restart with `python main.py --thread <same id>` and send any message... then think:
   why doesn't the old approval appear automatically? (Hint: `run_turn` only checks
   `snapshot.interrupts` after it streams. Bonus: make `main()` check for a pending
   interrupt on startup and offer to resume it.)

6. **Model-initiated HITL.** Ask something vague like `run a command for me`.
   *See:* `🙋 Agent asks:`. If the model doesn't ask, strengthen the `ask_human` docstring
   and observe how much the docstring changes behaviour.

### Level 3 — Loop engineering

7. **Hit the step budget.** `AGENT_MAX_ITERATIONS=2 python main.py`, then ask
   `list the files, read each one, and summarise them`.
   *See:* the agent stops calling tools and says what's unfinished. Find the line in
   `graph.py` that makes this happen (`tools_enabled = ...`).

8. **Trigger error-as-observation.** Ask `read the file does-not-exist.md`.
   *See:* a red error `←` line, then the model explaining or listing files instead.
   Now set `handle_tool_errors=False` in `graph.py` and repeat. What happens to the run?

9. **Remove the fuse.** In `tests/test_graph.py`, look at
   `test_iteration_budget_forces_final_answer`. Change `max_iterations` to 100 and
   `recursion_limit` in `drive()` to 10. Run it *(offline)*. Which layer stops it now, and how?

10. **Turn off reflection** with `AGENT_REFLECTION=false`. Compare speed and answer quality
    on a few tool-using questions. When is the extra LLM call worth it?

### Level 4 — Memory

11. **Cross-thread memory.** `remember that I'm learning LangGraph and prefer short answers`,
    then `/new`, then `what am I learning?`. *See:* `ⓜ recalled N memory item(s)`.
    Run `/memory` and `/forget <id>`, then ask again.

12. **Force compaction.** `AGENT_CONTEXT_BUDGET=300 python main.py`, chat for 4–5 turns.
    *See:* `⇢ context compacted`. Run `/state` to read the summary. What details survived?
    Edit `SUMMARIZE_PROMPT` to keep different things and compare.

13. **Semantic memory.** `ollama pull nomic-embed-text`, delete `data/store.sqlite`, run with
    `OLLAMA_EMBED_MODEL=nomic-embed-text`. Save "I drink green tea every morning", then in a
    new thread ask "what's my usual beverage?" (no shared words). Compare with keyword mode.

### Level 5 — Extend it (build something)

14. **New local tool.** Add a `word_count(path)` tool that reads a workspace file and counts
    words. Add it to `LOCAL_TOOLS`. No other change should be needed. Why?

15. **New MCP server.** Write `mcp_servers/todo_server.py` with FastMCP (`add_todo`,
    `list_todos`, `complete_todo`, stored in a JSON file). Register it in `mcp_servers.json`.
    Add `complete_todo` to `AGENT_RISKY_TOOLS`. You've just extended the agent without
    touching `graph.py`.

16. **Add a planning node.** Insert a `plan` node between `prepare_turn` and
    `compact_context` that asks the model for a 1–5 step plan, stores it in state, and
    shows it in the system prompt. Bonus: `interrupt()` to let the human approve the plan
    (plan-level HITL, in addition to tool-level HITL).

17. **Token streaming.** Change `run_turn` to `stream_mode=["updates", "messages"]` and print
    tokens from the `agent` node as they arrive. Watch out: drafts rejected by the critic
    will have been streamed too — how would you handle that in a UI?

18. **Write a test** *(offline)* for exercise 14 or 15, using `ScriptedChatModel` the same
    way the existing tests do.

---

## Self-check questions

Answer these without looking; then verify in the code.

1. Why does the system prompt never get stored in `state["messages"]`?
2. What would break if `approval_gate` sent an HTTP request *before* calling `interrupt()`?
3. A rejected tool call still produces a `ToolMessage`. Why not just delete the call?
4. Why does compaction move its cut point back to a `HumanMessage`?
5. What is the difference between `thread_id` and `user_id` in this project?
6. Name the five loop-engineering layers from softest to hardest.
7. Why is approval a config policy rather than something the model decides?
8. Where does an MCP tool's description come from, and who reads it?
9. Why can tests run the full graph without Groq API access?
10. When would you choose background memory extraction over the `save_memory` tool?

<details>
<summary>Short answers</summary>

1. It's rebuilt every step from current state (fresh summary, memories, budget). Storing it would duplicate and go stale.
2. Nodes re-run from the top on resume, so the request would be sent twice.
3. Every tool call must be answered by a ToolMessage with its id, or the history is invalid for chat APIs; and the model needs to know *why* it didn't run.
4. So an AIMessage with tool calls is never separated from its ToolMessages.
5. `thread_id` = which conversation (checkpointer key, short-term). `user_id` = whose long-term memory (Store namespace).
6. Budget awareness → forced final answer → error-as-observation → loop guard → recursion_limit.
7. Safety controls must not depend on the thing being controlled; a model could be wrong or prompt-injected.
8. From the server function's docstring via FastMCP; the model reads it (through bind_tools) to decide when to call the tool.
9. The graph depends only on the `BaseChatModel` interface; tests inject a scripted model. Checkpointer/store are injected too.
10. When you want zero added latency and consistent extraction rules, and you're fine with memories appearing after the turn rather than during it.
</details>
