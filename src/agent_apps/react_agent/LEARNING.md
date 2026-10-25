# Learning Guide

# 学习指南

Follow one familiar story: record an expense, inspect the ledger, compute a share, correct a mistake, and remember a reporting preference. Run the first session below, then read the code and continue with the exercises. English appears first and Chinese below throughout the teaching material.

围绕一个熟悉的故事学习：记一笔支出、查看账本、计算占比、纠正错误、记住报告偏好。先完成下面的首次体验，再阅读代码并继续动手练习。教学说明统一英文在上、中文在下。

## First session

## 首次体验

Start with the quick-start commands in [README.md](README.md), using `--user practice` for a separate ledger. Spend the first 15–20 minutes observing one tool call and one approved write. Expenses are USD only; replace the example details with your own real values.

按 [README.md](README.md) 的快速启动步骤运行，用 `--user practice` 创建独立练习账本。先花 15–20 分钟观察一次工具调用和一次审批写入。仅支持美元支出；记账示例请替换为你自己的真实信息。

1. Ask “What percentage is $12.50 of $50?” Find `→ calculate_share`, its `←` result, and the final 25.00% answer. A critic message may follow the tool result.

   问“12.50 美元占 50 美元的百分之几？”找到 `→ calculate_share`、`←` 工具结果和最终 25.00% 的回答。工具返回后可能还有反思检查。

2. Request one real expense, with a date and category. At approval choose `r` to reject it first, then query the ledger to see that it was not added. Request it again and choose `a` to save it.

   用明确日期和分类录入一笔真实支出。第一次审批选择 `r` 拒绝，再查询账本，确认没有新增。重新提出这笔记账请求，选择 `a` 批准保存。

3. Run `/tools` to see the approval marks, `/state` to see the last turn’s counters, and `/graph` to see where the events came from. Then start the short reading path below.

   运行 `/tools` 查看审批标记、`/state` 查看上一轮计数、`/graph` 查看事件对应的节点，再开始下面的阅读路线。

## Reading order

## 阅读顺序

Read only the named function or section at each early step. Return to the complete graph after the basic decide → act → observe loop is clear.

前几步只读指定函数或片段。理解“决策 → 执行 → 观察”循环后，再通读完整图。

| Step<br>步骤 | File or section<br>文件或片段 | Focus<br>重点 |
|---|---|---|
| 1 | `agent/tools.py`: `calculate_share` | A Python function becomes a tool through its types and docstring<br>类型提示和 docstring 如何把 Python 函数变成工具 |
| 2 | `agent/graph.py`: `agent`, `route_after_agent`, `ToolNode` wiring | Model chooses → tool executes → result returns → model chooses again<br>模型决策 → 工具执行 → 结果返回 → 再次决策 |
| 3 | `agent/state.py`, `tests/test_graph.py`: `test_react_loop_with_local_tool` | Messages, reducers, State vs Context; a complete two-step trace<br>消息、reducer、状态与上下文；完整的两步轨迹 |
| 4 | `agent/graph.py`: `approval_gate`, `enforce_hitl`; `main.py`: `run_turn`, `resume_pending` | Approve/edit/reject, interrupt, checkpoint and resume<br>审批、编辑、拒绝、中断、检查点与恢复 |
| 5 | `mcp_servers/expense_server.py`, `agent/mcp_client.py` | The same tool interface across a process boundary; persistence and validation<br>跨进程的相同工具接口；持久化和校验 |
| 6 | `agent/config.py`; graph budget and `loop_guard` sections | Per-turn steps, errors, repetition warnings and recursion limit<br>每轮步数、错误、重复警告和递归限制 |
| 7 | `agent/memory.py`, memory tools, `prepare_turn`, `compact_context` | ToolRuntime, user namespaces, recall and three memory layers<br>运行时注入、用户命名空间、召回和三层记忆 |
| 8 | `agent/prompts.py`; `reflect` in `agent/graph.py` | Dynamic context and bounded answer revision; then read the whole graph<br>动态上下文与受限的回答修正，然后通读整张图 |
| 9 | `agent/llm.py`, remaining `main.py` sections | Model factory, application wiring, streaming and inspection commands<br>模型工厂、应用组装、事件流和检查命令 |
| 10 | `tests/fake_model.py`, `tests/test_expenses.py`, `tests/test_console.py` | Scripted trajectories, real MCP and real process recovery<br>脚本轨迹、真实 MCP 和真实进程恢复 |

Markers: `📘 LEARN` explains a concept; `⚠ PITFALL` points out a trap; `🧪 TRY` proposes an experiment. Follow the graph edges to trace execution; the README includes the diagram.

标记说明：`📘 LEARN` 解释知识点，`⚠ PITFALL` 提醒易错点，`🧪 TRY` 给出实验。沿图中的边追踪执行路径，README 提供图示。

## Core concepts

## 核心概念

**ReAct:** decide → call tools → read observations → decide again. Native function calling provides structured calls; there is no need to parse textual “Thought/Action” blocks. One AI message can contain independent calls executed in parallel. An answer without tool calls leaves the inner loop.

**ReAct：** 决策 → 调用工具 → 读取观察结果 → 再决策。原生 Function Calling 提供结构化调用，不需要解析文字形式的“思考/行动”段落。一条 AI 消息可包含并行的独立调用；没有工具调用的回答结束内层循环。

**Loop engineering:** budget reminders, a final step without tools, errors as observations, repetition/error-streak warnings, and a recursion fuse. Reflection forms a separate outer loop, but every rewrite still consumes the same agent-step budget. At exhaustion, keep the final answer and skip reflection. Counts are per user turn and survive pauses.

**循环工程：** 预算提醒、最后一步禁用工具、错误反馈、重复/连续错误警告、递归保险丝。反思形成独立外层循环，但每次重写仍消耗同一个 Agent 步数预算。预算耗尽后保留最终回答并跳过反思。计数按用户轮次计算，暂停时不会丢失。

**HITL:** policy-triggered approval and model-triggered questions both use `interrupt()`. Resumption reruns the node; keep preceding code free of side effects. Every rejected call still needs a matching result to preserve valid message history.

**人工介入：** 策略触发的审批和模型触发的提问都使用 `interrupt()`。恢复时节点重新执行，因此前面的代码不能产生副作用。拒绝调用也必须生成匹配结果，保证消息历史合法。

**MCP:** a separate service describes and executes tools. The adapter makes remote tools look like local BaseTools. The service knows nothing about the model or graph. stdio is a transport, not a shell command tool exposed to the model.

**MCP：** 独立服务描述并执行工具，适配器使远程工具表现为本地 BaseTool。服务不知道模型或图的存在。stdio 是传输方式，不是向模型开放 shell 命令工具。

**Memory:** checkpoints persist one conversation, compaction summarizes older turns, and Store retains user preferences across threads. The ledger is a separate business database. Rebuild the system prompt from these sources each step instead of storing stale prompts.

**记忆：** 检查点保存单个会话，压缩将旧轮次总结，Store 跨会话保存用户偏好。账本是独立的业务数据库。每步根据这些信息重建系统提示词，避免持久化过期提示词。

## Exercises

## 动手练习

Use your own expense data. Write exercises change your local ledger after approval. For an isolated practice ledger, start with a separate user such as `uv run react-agent --user practice`. Offline tests automatically use temporary directories. Paired prompts below are alternatives.

使用你自己的支出数据。写操作练习在批准后会修改本地账本。需要独立练习账本时可使用 `uv run react-agent --user practice`。离线测试自动使用临时目录。下面的双语提示是同一请求的两种表达。

1. **Observe a local tool.** Ask “What percentage is $12.50 of $50?” Look for `calculate_share`, its observation and the final 25.00% answer. Use `/state` to inspect iterations; the exact count can vary with the model.

   **观察本地工具。** 问“12.50 美元占 50 美元的百分之几？”观察工具调用、结果和最终 25.00% 的回答。使用 `/state` 查看迭代次数，真实模型的步数可能不同。

2. **Inspect checkpoints.** Run `/history`. Match snapshots to super-steps; a tool call takes several nodes, not one checkpoint. State updates are partial and merged by reducers.

   **检查检查点。** 运行 `/history`，把快照与 super-step 对应起来。一次工具调用跨越多个节点，不等于一个检查点；节点返回局部更新，由 reducer 合并。

3. **Trace the graph.** Run `/graph` and match each node and edge to `graph.py`. Find both conditional routing and `Command(goto=..., update=...)`.

   **追踪图。** 运行 `/graph`，对照 `graph.py` 查找节点和边，分别定位条件路由以及 `Command(goto=..., update=...)`。

4. **Approve, edit, reject.** Record one real expense. At approval, edit its amount using a full JSON argument object. Query the saved record, then request another write and reject it. Compare ledger state and message history.

   **批准、编辑、拒绝。** 录入一笔真实支出，在审批时用完整 JSON 参数修改金额，再查询保存结果。提出另一笔写操作并拒绝，比较账本和消息历史的变化。

   **Complete edit example.** Suppose the pending `add_expense` arguments are `{"amount":"12.50","spent_on":"2026-10-25","category":"餐饮","note":"Lunch"}`. Choose `e`. At the next prompt paste this complete **single-line** JSON object to change only the amount:

   **完整编辑示例。** 假设待审批的 `add_expense` 参数如上，选择 `e`。在下一次输入提示处粘贴下面这份完整的**单行** JSON，只把金额改为 11.80：

   ```json
   {"amount":"11.80","spent_on":"2026-10-25","category":"餐饮","note":"Lunch"}
   ```

   This replaces the whole argument object. Query the record afterwards: its amount should be USD 11.80; the date, category and note should be unchanged. Reopen the example with your own values when practicing. Omitting required fields such as `spent_on` produces a validation error rather than a partial edit.

   这会替换整个参数对象。随后查询记录：金额应为 11.80 美元，日期、分类和备注保持原值。实际练习时使用你自己的信息。缺少 `spent_on` 等必填字段会返回校验错误，不会按局部修改处理。

5. **Resume a durable pause.** At approval, note the thread ID and press Ctrl+C to quit without submitting another line. Restart using the same user and `--thread ID`; approval appears before a new input prompt. Confirm once and check that only one record was created. The console integration test starts a real process, interrupts it, and reopens the same checkpoint to verify this offline.

   **恢复持久化暂停。** 在审批处记下 thread ID，按 Ctrl+C 退出，无需再输入一行，用同一用户和 `--thread ID` 重启。审批应在新输入前出现；确认一次并检查只新增一条记录。控制台集成测试会启动真实进程、中断退出，再重新打开同一检查点来离线验证这个过程。

6. **Let the model ask.** Say “Record the expense, but ask me for the amount first.” Observe `ask_human` and its return value. Compare its model-triggered interrupt with policy-triggered approval. Docstrings influence when tools are chosen.

   **让模型提问。** 说“帮我记一笔，但先问我金额”。观察 `ask_human` 及返回值，比较模型主动提问和策略审批。工具 docstring 会影响模型何时调用它。

7. **Exhaust the step budget.** Start with `AGENT_MAX_ITERATIONS=2 uv run react-agent --user practice`. Request a weekly summary and a food percentage. If the steps are insufficient, the agent must explain what remains unfinished. Find the unbound-model call.

   **耗尽步骤预算。** 用上述较低预算启动，要求本周汇总及餐饮占比。步骤不足时 Agent 应说明未完成部分，找到最后一步不绑定工具的代码。

8. **Treat errors as observations.** Run the offline error test with `-k tool_error`. It deliberately asks the local tool for a percentage with a zero denominator. Check the error ToolMessage and model recovery. Normal prompts should avoid this call when total is zero.

   **把错误当成观察结果。** 用 `-k tool_error` 运行离线测试，脚本故意以零为分母调用工具，观察错误 ToolMessage 和恢复流程。正常提示词应避免总额为零时调用占比工具。

9. **Exercise warnings and the hard fuse.** Run tests selected by `-k 'loop_guard or error_streak or recursion_limit'`. Compare repeated identical calls, distinct failing calls, and `GraphRecursionError`. A warning steers; the hard fuse stops execution.

   **观察警告与硬限制。** 运行对应测试，比较相同调用重复、不同调用连续失败和 `GraphRecursionError`。警告负责引导，硬限制负责停止。

10. **Compare reflection.** Toggle `AGENT_REFLECTION=false` and compare a summary response. Run `-k reflection` for a deterministic revision. Reflection is skipped without tool use or remaining agent steps; it never rolls back writes.

    **比较反思。** 关闭反思后比较汇总回答，用 `-k reflection` 确定性地观察修改。没有工具调用或没有剩余 Agent 步数时跳过反思；反思永远不会回滚已执行写入。

11. **Cross-thread preferences.** Say “Remember that I want category totals first,” run `/new`, then ask about report formatting. Inspect `/memory` and use `/forget ID`. Switch `--user` to see separate preferences and a separate ledger.

    **跨会话偏好。** 说“记住，我希望先看分类汇总”，运行 `/new` 后询问报告格式。通过 `/memory` 查看、`/forget ID` 删除。切换 `--user` 后，偏好和账本均独立。

12. **Force compaction.** Start with `AGENT_CONTEXT_BUDGET=300`, chat for several turns, and inspect `/state`. Lower `keep_recent_messages` for a stronger experiment. Check that decisions and IDs survive, and that AI tool calls are never separated from their results.

    **触发压缩。** 调低 token 预算，多聊几轮并检查 `/state`；需要更强实验时可调低保留消息数。观察摘要是否保留决策和记录 ID，以及工具调用和结果是否成对保留。

13. **Understand keyword recall.** Store several preferences. Compare “category totals” with “grouped spending.” Try Chinese synonyms too. Inspect `_tokens` and top-k ranking; fallback memories can mask a missed keyword match.

    **理解关键词召回。** 保存多个偏好，对比不同近义表达，并试试中文同义词。检查 `_tokens` 和 top-k 排序；兜底记忆可能让关键词未匹配看起来仍然召回成功。

14. **Add a simple local tool.** Implement `remaining_budget(budget, spent)` as an optional pure function. Specify its same-currency and overspending behavior. Register it in `LOCAL_TOOLS`; no graph changes should be needed.

    **添加简单本地工具。** 选做 `remaining_budget(budget, spent)` 纯函数，明确同币种要求和超支时的返回方式。注册到 `LOCAL_TOOLS`，无需改图。

15. **Add another MCP service.** As an extension, build a small monthly-budget service with `set_budget` and `get_budget`. Persist real user inputs; add its configuration and put writes in the approval policy. Explain why the model still sees ordinary tools.

    **添加 MCP 服务。** 扩展一个月度预算服务，提供设置和查询预算，持久化用户实际输入。在配置中注册，并将写操作加入审批策略。解释为什么模型看到的仍是普通工具。

16. **Add a planning node.** As an extension, put a `plan` node before `compact_context`, store a short plan and inject it into the prompt. Optionally interrupt for plan approval. Contrast approving a plan with approving actual write arguments.

    **添加规划节点。** 选做：在压缩前加入 `plan`，保存简短计划并注入提示词，也可暂停让用户确认计划。比较批准计划和批准实际写入参数的区别。

17. **Stream tokens.** As an extension, try `stream_mode=["updates", "messages"]`. Only render the intended model node’s tokens. Consider how to display a draft that the critic later rejects. The default app streams node updates, not individual tokens.

    **逐 token 流式展示。** 选做：组合两种流模式，仅显示目标模型节点的 token，并考虑如何处理后续被反思否决的草稿。当前应用默认展示节点更新，不是逐 token 输出。

18. **Write a meaningful offline test.** Test the new budget tool/service with `ScriptedChatModel`. Verify observable results and side effects. Study the existing timeout, parallel mixed-batch, pagination and user-isolation tests. Fake model responses are test fixtures, not fake production expenses.

    **编写有意义的离线测试。** 用脚本模型测试新增预算工具或服务，验证可观察结果和副作用。阅读现有超时、并行混合调用、分页和用户隔离测试。假模型响应是测试夹具，不是正式运行的虚假账目。

## Self-check

## 自测问题

1. Why rebuild SystemMessage instead of persisting it?

   为什么重建而不持久化系统提示词？
2. What happens to code before interrupt on resume?

   恢复时 interrupt 之前的代码会怎样？
3. Why retain a ToolMessage for a rejected call?

   为什么拒绝调用也要保留工具结果？
4. Why compact at a HumanMessage boundary?

   为什么按用户轮次边界压缩？
5. How do thread_id and user_id differ?

   会话 ID 和用户 ID 有何区别？
6. What are the five loop-control layers?

   循环控制的五层分别是什么？
7. Why does policy, not the model, enforce approval?

   为什么由策略而非模型强制审批？
8. Where does an MCP tool description come from?

   MCP 工具描述来自哪里？
9. What do offline tests prove, and what do they not prove?

   离线测试能证明什么，不能证明什么？
10. Why are preferences and expenses stored separately?

   为什么偏好与账目分开保存？
11. Why must summaries ignore pagination limits?

   为什么汇总不能受分页限制？
12. Does a tool timeout or failed critic undo a write?

   工具超时或反思失败会撤销写入吗？

<details>
<summary>Answers / 参考答案</summary>

1. Context changes each step; saved prompts become stale and duplicate information.<br>上下文每步变化，保存的提示词会过时并重复信息。
2. The node restarts; preceding side effects could happen twice.<br>节点从头执行，前面的副作用可能发生两次。
3. Chat APIs need matching call/result IDs; the model must learn why it was rejected.<br>聊天 API 要求调用与结果 ID 对应，模型也需要知道拒绝原因。
4. It preserves complete call/result groups.<br>确保工具调用与结果完整保留。
5. A thread identifies one conversation; a user owns preferences and a ledger.<br>会话标识一段对话，用户拥有偏好和账本。
6. Reminder, final step without tools, error observation, loop warnings, recursion fuse.<br>预算提醒、最后一步禁用工具、错误反馈、循环警告、递归保险丝。
7. Authorization must be deterministic rather than decided by model output.<br>授权必须确定执行，不能由模型输出决定。
8. The server function’s docstring, adapted into a tool schema.<br>来自服务端函数 docstring，经适配形成工具 schema。
9. They verify mechanisms and business rules, not live-model answer quality.<br>验证机制和业务规则，不保证真实模型的回答质量。
10. The ledger is authoritative structured data; memory is recallable user context.<br>账本是权威结构化数据，记忆是可召回的用户上下文。
11. A page contains only some rows; aggregate the complete filtered dataset.<br>一页只有部分记录，必须对全部筛选结果汇总。
12. No. Inspect the ledger; corrections are new approved operations.<br>不会。先查账本，纠正需要新的已审批操作。

</details>
