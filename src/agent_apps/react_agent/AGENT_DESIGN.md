# Agent Loops and Workflow Design

# Agent 循环与工作流设计

This note explains the design choices behind the Ledger expense assistant: a hand-written `StateGraph` with model calls, `create_agent`, and `create_deep_agent`. The central question is **which layer owns each decision and execution loop**, rather than which API is more powerful. English appears first, followed by Chinese.

本文围绕 Ledger 记账助手，比较手写 `StateGraph + LLM`、`create_agent` 和 `create_deep_agent`。核心问题是：**每个决策和执行循环由哪一层管理**，而不是哪个 API 更高级。全文采用英文在上、中文在下的形式。

Scope: the app in this directory. The repository also contains other agent examples. This is a design reference, not a record of a completed migration or a performance benchmark.

范围：当前目录下的应用；仓库中还有其他 Agent 示例。本文是设计参考，不代表已经完成框架迁移或性能对比。

Verified on 2026-10-25 against local `langchain==1.4.6`, `langgraph==1.2.14`, and `deepagents==0.7.28`, with official references linked below. Defaults and extension APIs can change between versions.

核对日期为 2026-10-25；本地版本为 `langchain==1.4.6`、`langgraph==1.2.14`、`deepagents==0.7.28`，官方参考链接见文末。不同版本的默认行为和扩展 API 可能变化。

## 1. A model call, an agent loop, and a business workflow

## 1. 模型调用、Agent 循环与业务工作流

These are three different units of work:

这三者代表不同粒度的工作：

| Unit / 单位 | Responsibility / 职责 |
|---|---|
| Model call / 模型调用 | Produce one response, which may request tools. / 生成一次响应，响应可能包含工具调用请求。 |
| Agent loop / Agent 循环 | Repeatedly call the model, execute requested tools, and feed results back until completion or interruption. / 反复调用模型、执行工具并回传结果，直到完成或中断。 |
| Business workflow / 业务工作流 | Define stages, allowed transitions, approvals, dependencies, and completion conditions. A stage may contain one model call or an entire agent. / 定义阶段、允许的跳转、审批、依赖和完成条件；一个阶段可以包含一次模型调用，也可以包含完整 Agent。 |

An agent does not have to be created by a function named `create_agent`. The current app already implements an agent: the model selects actions, tools perform them, and the graph feeds observations back into the next decision.

Agent 不必通过名为 `create_agent` 的函数创建。当前应用已经实现了 Agent：模型选择动作，工具执行动作，图把观察结果交回模型，供下一步决策使用。

## 2. What the current app builds

## 2. 当前应用实际构建了什么

In [agent/graph.py](agent/graph.py), `build_graph` assembles a single primary ReAct agent with supporting nodes. The entry point in [main.py](main.py) injects a model, local and MCP tools, a checkpointer, and a long-term Store.

在 [agent/graph.py](agent/graph.py) 中，`build_graph` 组装了一个主 ReAct Agent 及其辅助节点。[main.py](main.py) 注入模型、本地与 MCP 工具、Checkpointer 和长期 Store。

| Node / 节点 | Role / 作用 |
|---|---|
| `prepare_turn` | Reset per-turn state and recall user preferences. / 重置本轮状态，召回用户偏好。 |
| `compact_context` | Summarize older messages when needed. / 必要时调用模型压缩旧消息。 |
| `agent` | Make one model call and return its response plus the iteration count. / 调用一次模型，返回响应及循环计数。 |
| `approval_gate` | Pause for approve/edit/reject decisions on configured write tools. / 对配置的写工具暂停，等待批准、编辑或拒绝。 |
| `tools` | Execute local and MCP tools under the tool-call policy. / 按工具调用策略执行本地与 MCP 工具。 |
| `loop_guard` | Produce warnings for repeated calls or consecutive failures. / 对重复调用或连续错误生成警告。 |
| `reflect` | Review the draft and route to revision or completion. / 审核回答草稿，决定修改或结束。 |

The complete topology is shown in the [README](README.md#3-architecture) and in the comment immediately before `compile()` in `agent/graph.py`. `loop_guard` itself issues warnings; the step budget and recursion limit provide separate execution bounds. Reflection can revise an answer but cannot undo a ledger write.

完整拓扑见 [README](README.md#3-architecture)，以及 `agent/graph.py` 中 `compile()` 前的注释图。`loop_guard` 本身只生成警告；步数预算和递归上限分别约束执行。反思能够修改回答，但不能撤销已经发生的账本写入。

### StateGraph initialization and conditional edges

### StateGraph 初始化与条件边

```python
g = StateGraph(AgentState, context_schema=AgentContext)
```

This creates a graph builder. `AgentState` defines shared state fields and merge rules. `AgentContext` describes per-run inputs such as `user_id`; the caller supplies their values through `context=...`. The context is not checkpointed with state. Adding nodes and edges defines the topology; `compile()` produces the executable graph. Neither this constructor nor a node name creates an independent agent by itself. See the [StateGraph reference](https://reference.langchain.com/python/langgraph/graph/state/StateGraph).

这行代码创建图构建器。`AgentState` 定义共享状态字段及合并规则；`AgentContext` 定义 `user_id` 等单次运行输入的结构，实际值由调用方通过 `context=...` 传入，Context 不随 State 保存到检查点。添加节点和边定义拓扑，`compile()` 生成可执行图。这个构造函数和节点名称本身都不代表创建了一个独立 Agent。参见 [StateGraph 参考](https://reference.langchain.com/python/langgraph/graph/state/StateGraph)。

```python
g.add_conditional_edges(
    "agent", route_after_agent, ["approval_gate", "tools", "reflect", END]
)
```

After `agent` updates state, `route_after_agent` reads it and returns a destination. The list is an identity mapping of possible destinations, not an execution sequence. This router returns one destination at a time. It is a routing function, not a graph node. See the [conditional-edge reference](https://reference.langchain.com/python/langgraph/graph/state/StateGraph/add_conditional_edges).

`agent` 更新状态后，`route_after_agent` 读取状态并返回目的地。列表是可能目的地的同名映射，不是执行顺序。当前路由函数每次返回一个目的地；它是判断函数，不是图节点。参见 [条件边参考](https://reference.langchain.com/python/langgraph/graph/state/StateGraph/add_conditional_edges)。

### Single agent versus multiple agents

### 单 Agent 与多 Agent

The current app has one primary action-selection loop. `reflect` is a reviewer step, and `compact_context` may also call an LLM; additional calls or role prompts alone do not establish several independently operating agents. The critic can use a separate model, but defaults to the main model. A typical multi-agent design gives specialized workers their own instructions, tools or loops and a delegation/handoff protocol. Sharing a model does not prevent that design, and workers do not have to run in parallel.

当前应用只有一个主动作决策循环。`reflect` 是审核步骤，`compact_context` 也可能调用 LLM；增加模型调用次数或角色提示词，本身不能说明存在多个独立工作的 Agent。审核模型可以单独注入，默认复用主模型。典型多 Agent 设计会给专业工作者分别配置指令、工具或执行循环，并定义委派或交接协议；它们可以共用模型，也不必并行运行。

The separate [multi-agent example](../agent_by_langgraph/multi_agent.py) configures a lead and a research subagent. That is a different app, not part of this Ledger graph.

另一个目录中的 [多 Agent 示例](../agent_by_langgraph/multi_agent.py) 配置了主 Agent 与研究子 Agent，属于另一个应用，不是当前 Ledger 图的一部分。

## 3. What create_agent replaces

## 3. create_agent 接管什么

The current model step is essentially:

当前模型步骤的核心是：

```python
model_with_tools = model.bind_tools(tools)
# Inside the agent node / 在 agent 节点中：
response = await model_with_tools.ainvoke(messages)
```

`bind_tools` exposes tool schemas to the model. A normal tool-capable chat-model call returns an `AIMessage`, possibly containing `tool_calls`; it does not execute these application tools. Our graph performs execution and the next model call. Thus **the current model already chooses tools autonomously within the application's constraints**.

`bind_tools` 把工具 schema 提供给模型。普通的支持工具调用的聊天模型调用返回 `AIMessage`，其中可能包含 `tool_calls`，但不会执行这些应用工具。工具执行和下一次模型调用由当前图驱动。因此，**当前模型已经能够在应用约束内自主选择工具**。

With `create_agent`, the framework builds and compiles this loop:

使用 `create_agent` 时，框架负责构建并编译这个循环：

```python
from langchain.agents import create_agent

# Construction sketch; model and tools are injected dependencies.
# 构建示意：model 和 tools 是已准备好的依赖。
expense_agent = create_agent(
    model=model,
    tools=tools,
    system_prompt="Help the user manage expenses using the provided tools.",
)
```

It supplies a tool-calling ReAct-style loop: model decision → tool execution → observation → next decision. It does not require textual `Thought / Action / Observation` blocks or disclosure of internal reasoning. Without tools there is no tool-execution loop. See the [factory reference](https://reference.langchain.com/python/langchain/agents/factory/create_agent).

它提供工具调用式的 ReAct 循环：模型决策 → 工具执行 → 读取观察结果 → 再次决策。不要求输出文字形式的 `Thought / Action / Observation`，也不需要展示内部推理。没有工具时，就没有工具执行循环。参见 [工厂函数参考](https://reference.langchain.com/python/langchain/agents/factory/create_agent)。

Replacing the model call inside our existing `agent` node with a complete agent invocation is not a drop-in migration. The inner agent could execute tools before returning, while our outer `approval_gate` and `loop_guard` expect to intervene between decisions. Approval and budget policies must move to an appropriate inner extension point or remain enforced at the execution boundary.

不能直接把当前 `agent` 节点中的一次模型调用替换成完整 Agent 调用，就认为迁移完成。内层 Agent 可能在返回前已经执行工具，而当前外层 `approval_gate` 和 `loop_guard` 原本要在决策之间介入。审批和预算策略必须迁移到合适的内层扩展点，或继续在执行边界强制实施。

## 4. Outer StateGraph: LLM node versus agent node

## 4. 外层 StateGraph：LLM 节点与完整 Agent 节点

**The outer graph has the same orchestration primitives in both cases.** Either node can connect to ordinary edges, conditional edges and loops. Adding a complete agent does not make the outer graph inherently more expressive. The difference is the amount of work performed inside one node and where control returns.

**两种情况下，外层图拥有相同的编排能力。** 两类节点都可以连接普通边、条件边和回路。放入完整 Agent 不会让外层图天然更强；区别在于一个节点内部完成多少工作，以及控制权何时交回。

| Boundary / 边界 | LLM node / LLM 节点 | Complete agent node / 完整 Agent 节点 |
|---|---|---|
| Normal work per invocation / 正常单次调用工作量 | One model call. / 一次模型调用。 | Potentially several model and tool calls. / 可能包含多次模型与工具调用。 |
| Tool loop owner / 工具循环管理者 | Outer graph. / 外层图。 | Inner agent graph. / 内层 Agent 图。 |
| Where per-step policies belong / 每步策略放在哪里 | Explicit outer nodes and execution wrappers. / 显式外层节点和执行包装。 | Inner middleware or tool execution policies. / 内层 middleware 或工具执行策略。 |
| Typical return / 常见返回内容 | An `AIMessage` wrapped into a state update by our node. / 由当前节点包装为状态更新的 `AIMessage`。 | An agent output state, usually including accumulated messages. / Agent 输出状态，通常包含累积消息。 |

An inner agent can stream events and pause through interrupts; it is not unobservable. However, an outer edge after that node is not a callback after every internal tool call. Align input/output schemas or add an adapter, and deliberately configure checkpoint scope and resume behavior. The official [composition example](https://docs.langchain.com/oss/python/langchain/middleware/overview) shows agents inside larger workflows.

内层 Agent 可以流式输出事件，也可以通过 interrupt 暂停，并非不可观察。但节点后面的外层边，不会在每次内部工具调用后自动执行。组合时需要对齐输入输出结构，或添加适配函数，并明确配置检查点作用域和恢复行为。官方 [组合示例](https://docs.langchain.com/oss/python/langchain/middleware/overview) 展示了如何将 Agent 放进更大的工作流。

Use an LLM node when the outer graph should control each decision/action boundary. Use a complete agent node when the stage is an independently solvable task, such as “research this account” or “produce this report,” and its internal loop should be encapsulated.

如果外层图需要控制每次决策与动作之间的边界，就使用 LLM 节点。如果一个阶段代表能够独立完成的任务，例如“研究这个客户”或“生成这份报告”，并且希望封装其内部循环，就使用完整 Agent 节点。

## 5. Customizing the loop versus redesigning its topology

## 5. 自定义循环行为与重设计图结构

Both factories expose extension points; they are not closed black boxes. `create_agent` supports middleware hooks around model and tool calls and at invocation boundaries. Hooks can apply state updates and supported routing controls. Deep Agents also accepts middleware and configuration for its backend, subagents and state. See [custom middleware](https://docs.langchain.com/oss/python/langchain/middleware/custom) and [Deep Agents customization](https://docs.langchain.com/oss/python/deepagents/customization).

两个工厂函数都提供扩展点，并不是封闭黑盒。`create_agent` 支持模型和工具调用周围、以及单次任务边界上的 middleware hook；hook 可以更新状态，并使用框架支持的路由控制。Deep Agents 也支持 middleware，以及 backend、子 Agent 和状态等配置。参见 [自定义 middleware](https://docs.langchain.com/oss/python/langchain/middleware/custom) 和 [Deep Agents 自定义](https://docs.langchain.com/oss/python/deepagents/customization)。

| Extension / 扩展点 | Example / 示例 |
|---|---|
| `before_agent` / `after_agent` | Initialize or finalize an invocation. / 初始化或结束一次任务调用。 |
| `before_model` / `after_model` | Recall context, validate a response, update counters. / 召回上下文、校验响应、更新计数。 |
| `wrap_model_call` | Select a model, cache, retry, or transform a request. / 选择模型、缓存、重试或修改请求。 |
| `wrap_tool_call` | Validate a call, enforce policies, transform a result. / 校验调用、实施策略或处理结果。 |

These hooks work within the factory's execution model. They do not constitute a general API for supplying arbitrary nodes and edges. The factories return compiled graphs, not mutable `StateGraph` builders. Do not rely on modifying private builder internals to maintain a custom architecture.

这些 hook 工作在工厂定义的执行模型中，不等于可以传入任意节点和边的通用 API。工厂返回的是编译后的图，不是可继续随意添加节点和边的 `StateGraph` 构建器。不要依赖修改私有构建器内部结构来维护自定义架构。

### Can create_agent implement a custom “Pattern A”?

### create_agent 能否实现自定义的“A 模式”？

First distinguish a desired strategy from a mandatory execution structure:

先区分“希望模型采用的策略”和“必须执行的结构”：

| Pattern A / A 模式 | Suitable implementation / 合适的实现 |
|---|---|
| Prefer to query, calculate, then summarize; allow the model to adapt. / 希望先查询、再计算、再总结，允许模型调整。 | Prompt and tools can guide an agent. / 用提示词和工具引导 Agent。 |
| Always validate before a model/tool call, check output afterward, and enforce a call budget. / 每次模型或工具调用前必须校验，之后检查输出，并限制调用预算。 | Middleware and execution-boundary checks. / middleware 与执行边界校验。 |
| Mandatory stages, conditional branches, parallel joins and custom revision loops. / 强制阶段、条件分支、并行汇合和自定义修正回路。 | Explicit `StateGraph`, possibly containing agent nodes. / 显式 `StateGraph`，其中可以包含 Agent 节点。 |

A prompt saying “follow Pattern A” does not guarantee that every step occurs in the specified order. Middleware can implement substantial control, and a tool can encapsulate a whole workflow, but then that code enforces Pattern A. There is no factory parameter that imports an arbitrary workflow topology unchanged. If re-creating Pattern A requires fighting the default loop, keeping the explicit graph is usually clearer.

在提示词里写“请按照 A 模式执行”，不能保证每一步都发生、且严格按顺序执行。middleware 可以实现较强的控制，工具也能封装整个工作流，但此时保证 A 模式的仍然是这段控制代码。工厂没有把任意工作流拓扑原样导入的参数。如果实现 A 模式需要不断绕过默认循环，保留显式图通常更清晰。

## 6. What Deep Agents adds, including memory

## 6. Deep Agents 增加的能力与记忆边界

Deep Agents builds on the agent loop with filesystem tools, context management, and subagent facilities. These help with longer tasks and larger working contexts. Its long-term memory model uses files through configurable backends. More built-in capabilities do not by themselves improve Ledger's amount extraction or accounting correctness. See the [overview](https://docs.langchain.com/oss/python/deepagents/overview).

Deep Agents 在 Agent 循环上增加文件工具、上下文管理和子 Agent 等能力，适用于任务更长、工作上下文更大的场景。它通过可配置 backend，以文件形式管理长期记忆。内置能力更多，本身不会直接提高 Ledger 的金额提取或记账准确率。参见 [概览](https://docs.langchain.com/oss/python/deepagents/overview)。

| Concern / 关注点 | What must be explicit / 需要明确的事情 |
|---|---|
| Conversation continuity / 会话连续性 | Configure a checkpointer and reuse the intended thread ID; storage durability depends on the implementation. / 配置 Checkpointer 并复用相应 thread ID；是否跨进程持久化取决于存储实现。 |
| Context size / 上下文大小 | Summarization and large-result offloading manage prompt size; a summary is not a complete archive. / 摘要与大结果外置管理提示词大小；摘要不是完整存档。 |
| Cross-conversation preferences / 跨会话偏好 | Configure persistent memory storage, loading paths, user scoping and write policy. / 配置持久化记忆存储、加载路径、用户作用域与写入策略。 |
| Business records / 业务记录 | Keep expenses in the ledger database and query it for amounts and totals. / 支出保存在账本数据库，金额与合计从数据库查询。 |

By default, filesystem state is thread-scoped; it is not automatically a durable, cross-user memory database. `memory=[...]` identifies memory files to load; the backend determines where they live. A Store-backed or filesystem-backed setup can persist memory, but backend choice and namespace configuration matter. See [memory](https://docs.langchain.com/oss/python/deepagents/memory) and [backends](https://docs.langchain.com/oss/python/deepagents/backends).

默认文件状态属于当前线程，并不自动成为持久化、跨用户的记忆数据库。`memory=[...]` 指定加载哪些记忆文件，backend 决定文件存在哪里。基于 Store 或文件系统的方案可以持久化记忆，但需要明确选择 backend 和配置命名空间。参见 [记忆](https://docs.langchain.com/oss/python/deepagents/memory) 与 [backend](https://docs.langchain.com/oss/python/deepagents/backends)。

Our existing [agent/memory.py](agent/memory.py) stores user preferences as records and retrieves them by keyword overlap. Switching to file memory changes the representation and retrieval behavior; it is not an automatic replacement. Context compression, stored preferences, and authoritative expense data must remain distinct.

当前 [agent/memory.py](agent/memory.py) 将用户偏好保存为记录，并按关键词重叠召回。改为文件记忆会改变表示和检索方式，并不能自动替换现有逻辑。上下文压缩、用户偏好和权威支出数据需要继续区分。

## 7. Recommendation for this app

## 7. 本项目的选型建议

**Keep the current explicit graph for the learning app. If building a simpler product variant, evaluate `create_agent + middleware` first. Deep Agents is an option when the scope grows to substantial file work, long-running research or delegated tasks.** These are architectural expectations, not measured rankings.

**当前学习应用保留显式图。如果构建更精简的产品版本，优先评估 `create_agent + middleware`。当范围扩展到大量文件处理、长时间研究或任务委派时，再考虑 Deep Agents。** 这是架构预期，不是性能排名。

| Option / 方案 | Expected benefit here / 对当前项目的预期收益 | Tradeoff / 代价 |
|---|---|---|
| `StateGraph + LLM` | Explicit steps, inspectable policy boundaries, direct control over revision loops. / 步骤清晰、策略边界可检查、直接控制修正回路。 | Maintain routing, counters and execution policies ourselves. / 自行维护路由、计数和执行策略。 |
| `create_agent + middleware` | Reuse the standard loop and selected approval, summarization and limit components. / 复用标准循环，以及审批、摘要和次数限制组件。 | Adapt custom reflection, per-turn budgets, state and terminal resume behavior. / 适配自定义反思、每轮预算、状态和终端恢复逻辑。 |
| `create_deep_agent` | Reuse a broader context and delegation toolkit if those needs arise. / 相关需求出现后，可复用更完整的上下文和委派能力。 | Additional behavior/configuration and a possible memory-model migration. / 增加行为与配置，并可能需要迁移记忆模型。 |

Built-in middleware covers several relevant controls, but matching feature names does not establish identical semantics. For example, our per-turn counter resets, rejection handling and persisted terminal recovery must be checked individually. See the [middleware catalog](https://docs.langchain.com/oss/python/langchain/middleware/built-in).

内置 middleware 覆盖多项相关控制，但功能名称相同不代表语义完全一致。例如，当前每轮计数重置、审批拒绝处理和终端持久化恢复，都需要分别验证。参见 [middleware 列表](https://docs.langchain.com/oss/python/langchain/middleware/built-in)。

Changing the framework alone does not establish better results. Compare identical tasks with the same model and business tools: expense/date/category correctness, approval and recovery behavior, task completion, model/tool calls, latency and token cost. Preserve SQLite validation, SQL aggregation and user scoping in every variant.

仅更换框架不能说明效果更好。应使用相同模型与业务工具，对比相同任务的金额、日期和分类正确性，审批及恢复行为，任务完成率，模型和工具调用次数，延迟及 token 成本。所有版本都应保留 SQLite 校验、SQL 汇总与用户作用域。

## 8. A migration experiment, if we choose to do one

## 8. 如果决定迁移，如何进行对比实验

1. Retain the current implementation as the reference. Build a separate factory-based variant rather than replacing the model call in place.

   保留当前实现作为参考。另建工厂函数版本，不直接原地替换模型调用。

2. Reuse the MCP expense service and local tools. Preserve checkpointer/store configuration, context injection and per-user data separation.

   复用 MCP 记账服务和本地工具，保留 Checkpointer、Store、Context 注入与用户数据隔离。

3. Map each existing control to middleware or another explicit execution boundary. Decide whether the custom critic is still needed; keep its bounded revision behavior if it is.

   把每项现有控制映射到 middleware 或其他明确执行边界。评估是否继续需要自定义审核器；若保留，也保留其有限次数修正机制。

4. Adapt terminal events, approval payloads and resume handling. Use [tests/](tests/) as the source of behavioral requirements, without assuming internal node names remain identical.

   适配终端事件、审批数据格式和恢复处理。以 [tests/](tests/) 作为行为要求来源，不假设内部节点名称保持一致。

5. Compare read-only queries, approved/edited/rejected writes, missing-information clarification, restart during approval, new-thread preference recall and bounded error recovery. Evaluate on isolated ledgers, then choose based on behavior and maintenance cost.

   对比只读查询、批准/编辑/拒绝写入、缺失信息澄清、审批中重启、新会话偏好召回，以及有上限的错误恢复。在隔离账本上评估，再根据行为和维护成本选型。

## 9. Common misconceptions

## 9. 常见误解

| Misconception / 误解 | Correction / 更准确的理解 |
|---|---|
| “Without `create_agent`, the model cannot choose tools.” / “不用 `create_agent`，模型就不能自主选择工具。” | The current graph already uses model-selected tool calls. / 当前图已经使用模型自主生成的工具调用。 |
| “One graph node is one agent.” / “一个图节点就是一个 Agent。” | A node is a unit of execution; it can contain deterministic code, one model call or a whole agent. / 节点是执行单元，可以包含普通代码、一次模型调用或完整 Agent。 |
| “Multiple model calls mean multiple agents.” / “调用多次模型就是多 Agent。” | Distinguish action loops and delegation boundaries from call count. / 应看决策循环和委派边界，而不是调用次数。 |
| “Factories cannot be customized.” / “封装好的工厂不能自定义。” | They offer configuration and middleware, within a defined execution model. / 它们提供配置和 middleware，但有既定执行模型。 |
| “An outer graph makes every inner action an outer step.” / “套外层图后，每个内部动作都变成外层步骤。” | Inner steps remain inside the agent; streaming and interrupts expose events without changing edge semantics. / 内部步骤仍属于内层 Agent；事件流和中断不会改变外层边的执行语义。 |
| “A prompt can enforce an arbitrary workflow.” / “提示词可以强制执行任意工作流。” | Mandatory transitions require control code at the appropriate boundary. / 强制跳转需要在合适边界用控制代码保证。 |
| “Built-in memory means everything is saved forever.” / “内置 memory 就会永久保存所有内容。” | Persistence, scope, selection and retrieval remain explicit design choices. / 持久化、作用域、记忆选择与检索仍是设计选择。 |
| “A more capable framework necessarily gives more accurate accounting.” / “框架功能更全，记账一定更准确。” | Model/tool quality and business validation still determine correctness; measure the result. / 模型、工具与业务校验仍影响正确性，需要实际测量。 |

## 10. References and code map

## 10. 参考资料与代码入口

Official framework references are linked beside the claims they support. They describe supported APIs and intended usage, not comparative market share. No public adoption statistic or benchmark is claimed in this document.

官方框架参考已链接在相关说明旁，用于支持 API 能力和使用方式，不代表市场占比比较。本文不声称掌握公开采用率统计，也不提供未实施的基准结果。

| Local reference / 本地入口 | What to inspect / 阅读重点 |
|---|---|
| [README.md](README.md) | App scope, topology, configuration and verification. / 应用范围、拓扑、配置和验证方式。 |
| [LEARNING.md](LEARNING.md) | Guided exercises and reading order. / 学习路线和动手练习。 |
| [agent/graph.py](agent/graph.py) | Loop ownership, policy boundaries and routes. / 循环管理、策略边界和路由。 |
| [agent/state.py](agent/state.py) | Shared state versus per-run context. / 共享状态与单次运行上下文。 |
| [agent/memory.py](agent/memory.py) | Preference storage, user namespace and retrieval. / 偏好存储、用户命名空间与检索。 |
| [agent/tools.py](agent/tools.py) | Runtime injection, local tools and clarification. / 运行时注入、本地工具与澄清。 |
| [main.py](main.py) | Resource lifecycle, streaming and durable resume. / 资源生命周期、事件流与持久化恢复。 |
| [tests/](tests/) | Existing behavioral contracts. / 现有行为约束。 |
