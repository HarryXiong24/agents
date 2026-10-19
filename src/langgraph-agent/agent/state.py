"""Graph state and runtime context.

📘 LEARN — two kinds of data flow through a LangGraph run:

    ┌──────────────────┬───────────────────────────────┬──────────────────────────────┐
    │                  │ State (AgentState)            │ Context (AgentContext)       │
    ├──────────────────┼───────────────────────────────┼──────────────────────────────┤
    │ What             │ everything that changes       │ static info about this run   │
    │ Who writes it    │ nodes (by returning updates)  │ the caller, once             │
    │ Persisted?       │ yes, after every super-step   │ no                           │
    │ Passed how       │ graph.astream({"messages":…}) │ graph.astream(…, context=…)  │
    │ Example          │ messages, counters, summary   │ user_id, tenant, API keys    │
    └──────────────────┴───────────────────────────────┴──────────────────────────────┘

Rule of thumb: if it must survive a pause/restart or nodes need to change it → State.
If it identifies *who/what* the run is for and never changes mid-run → Context.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langgraph.graph import MessagesState


class AgentState(MessagesState):
    """Everything the graph carries between nodes (and persists via the checkpointer).

    📘 LEARN — reducers: each key has a rule for merging a node's update into the state.
      • `messages` (inherited from MessagesState) uses `add_messages`:
            return [new_msg]              → appended
            return [msg_with_existing_id] → that message is REPLACED   (used by approval_gate)
            return [RemoveMessage(id=…)]  → that message is DELETED    (used by compaction/reflect)
      • every other key below has no reducer → last write wins (plain overwrite).

    You could add custom reducers with `Annotated[list, operator.add]` (e.g. to
    accumulate a log), but overwrite is what we want for counters we reset each turn.

    ⚠ PITFALL: keys are optional at runtime — a fresh thread has none of them yet.
    That is why nodes read with `state.get("iterations", 0)` rather than `state["iterations"]`.
    """

    # --- memory management --------------------------------------------------------
    summary: str                      # rolling summary of compacted (deleted) history
    memories: list[str]               # long-term memories recalled for this turn

    # --- loop engineering (reset by prepare_turn at the start of every user turn) ---
    iterations: int                   # how many times the agent node ran this turn
    reflections: int                  # how many critic revisions happened this turn
    loop_warning: str                 # written by loop_guard, read by the system prompt
    critique: dict[str, Any] | None   # {"draft": ..., "feedback": ...} from the critic

    # --- human-in-the-loop ---------------------------------------------------------
    # tool_call_id -> {"action": "reject", "reason": ...}. Written by approval_gate,
    # read by the tools-node interceptor, cleared by loop_guard.
    hitl_decisions: dict[str, dict[str, Any]]


@dataclass
class AgentContext:
    """Static per-run context (not persisted). Passed via `graph.astream(..., context=...)`.

    Nodes get it as `runtime.context`, tools as `runtime.context` via `ToolRuntime`.
    Here it only scopes long-term memory: every user gets their own memory namespace.
    """

    user_id: str = "default"
