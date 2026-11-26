# Todo Agent 动态学习网站：开发交接与执行指令

## 1. 你的任务

你是负责把同一个待办助手的三种 Python 实现转化为交互教学网站的开发 Agent。
阅读本文件、项目规则和源码后，完成一个可本地运行、可实际操作的动态网页。
交付物是网站及其运行说明，不能只提交设计方案、静态文章或架构截图。

网站的主要叙事是：

> 一个最小的 ReAct Agent，怎样通过 V1–V11 逐步搭建为具有存储、检查点、
> 摘要、State 维护、中间件、审批、结构化输出、边界控制、MCP 和 Skills 的应用？
> 改用 create_agent 时，哪些工作移到了框架和中间件？
> 再改用 Codex SDK 时，哪些工作由 Codex runtime 执行，哪些业务规则仍由应用负责？

核心源码目录：

- 手动编排：src/agent_apps/todo_list_assistant_agent
- 工厂模式：src/agent_apps/todo_list_assistant_create_agent
- SDK 模式：src/agent_apps/todo_list_assistant_codex_sdk

**三个应用是同一个待办助手的三种实现。** 保留手动版 V1–V11 的搭积木主线，
从 V11 的最终架构进入两个并列的对照：`create_agent` 用框架生成图并通过中间件扩展，
Codex SDK 则让应用通过 SDK 使用已有的 Agent runtime。用相同业务输入对比三者，
重点看执行权、数据归属和约束入口如何变化。具体差异见第 8 节。

当前仓库根目录为 /Users/harryxiong24/Code/agents。
优先用相对路径组织引用，不把开发者机器路径硬编码进最终网站。
本文件已包含必要学习背景，不依赖另一份尚未创建的交接文档。

本文件用于指导后续的网站开发。本轮生成此文件本身不代表已完成网站。

## 2. 学习背景：先理解用户为什么需要这个网站

用户通过真实项目“搭积木”学习 Agent，而不是单纯寻找一个能聊天的产品。
用户已经逐步阅读过代码，持续追问某一行为什么存在、参数由谁提供、
函数何时执行、返回值由谁处理、状态何时保存。

讲解与界面需要始终围绕：

1. 这个阶段出现了什么问题？
2. 加入哪一块积木可以解决？
3. 它接在已有流程的什么位置？
4. 输入来自哪里，返回值流向哪里？
5. 哪一步更新 State，怎样合并，何时可被后续步骤读取？
6. 模型实际看到了什么，哪些对象只属于程序运行时？
7. 没有这块积木时会发生什么？

采用渐进式展开：初始界面先给清楚的主线，点击后再展开代码、JSON 和边界细节。
不要把几十个字段、所有版本说明和所有调用栈同时堆在首屏。
面向具备基础 Python 阅读能力、正在学习 Agent 框架的人，而非零基础 Python 课程。

网站界面和教学文案默认中文；Python API、类、函数、字段名称保留英文。
代码变量、源码注释遵守所在项目的英文约定。

## 3. 开发前必须阅读的资料

### 3.1 阅读顺序与事实来源

先读本文件，再读三个应用的 AGENTS.md，以及下面的当前文档：

- [手动版本规则](todo_list_assistant_agent/AGENTS.md)
- [手动版本当前用法](todo_list_assistant_agent/README.zh-CN.md)
- [V1–V11 学习记录](todo_list_assistant_agent/docs/VERSIONS.zh-CN.md)
- [create_agent 版本规则](todo_list_assistant_create_agent/AGENTS.md)
- [create_agent 当前用法](todo_list_assistant_create_agent/README.zh-CN.md)
- [手动图与 create_agent 对照](todo_list_assistant_create_agent/docs/COMPARISON.zh-CN.md)
- [Codex SDK 版本规则](todo_list_assistant_codex_sdk/AGENTS.md)
- [Codex SDK 当前用法](todo_list_assistant_codex_sdk/README.zh-CN.md)
- [三种实现对照](todo_list_assistant_codex_sdk/docs/COMPARISON.zh-CN.md)

之后沿各应用的启动、编排入口、工具执行、数据更新与持久化阅读源码和相关测试。

行为以当前源码为依据，历史演进以 VERSIONS 文档为依据。
若文档和代码冲突，记录差异并按代码校正网站，不为了配合展示而修改后端行为。
用户后续指令优先于本交接文件。

### 3.2 重点源码

手动版本：

- main.py、console.py、config/
- agent/graph.py、agent/state.py、agent/prompts.py
- agent/nodes/model.py、tools.py、summarize.py、draft.py
- agent/tools/、agent/middleware/
- agent/memory.py、agent/checkpoints.py
- agent/mcp.py、config/mcp.py、mcp_servers/pomodoro.py
- agent/skills.py、agent/tools/skills.py、skills/
- tests/test_hitl.py、test_budgets.py、test_draft.py、test_summarization.py
- tests/test_mcp.py、test_skills.py

create_agent 版本：

- main.py、console.py、config/
- agent/agent.py、agent/state.py、agent/tools/
- agent/middleware/ 中的所有职责模块
- agent/tools/draft.py、agent/tools/skills.py
- agent/mcp.py、agent/skills.py、agent/prompts.py
- tests/test_factory.py、test_mcp.py、test_skills.py

Codex SDK 版本（名称均相对于该应用目录）：

- `main.py::run`、`console.py::select_thread / chat`、`config.py::AppConfig` 和 `prepare_workspace`。
- `agent/runtime.py::open_thread / run_turn / chat_input / generate_draft`，定位 Thread、Turn、事件、SkillInput 和草案。
- `agent/transport.py::serve_tools`、`agent/gateway.py::ToolGateway / TurnScope / PendingCall`，定位协议、配额和业务审批。
- `agent/tools.py::LocalTools / validate_draft`、`agent/schemas.py`、`agent/storage.py::Store`，定位数据校验、候选与写入。
- `agent/mcp_client.py::connect_tools / RemoteTool`、`mcp.example.json`、`mcp_servers/pomodoro.py`，定位可选的上游 MCP。
- `agent/prompt_templates/`、`skills/`、`tests/test_business_flow.py` 和 `tests/test_runtime.py`。

### 3.3 必须先产出事实清单

开发时先建立结构化内容数据，至少记录：

- 每版新增、保留、替换的组件与学习目标。
- 当前节点、工具、辅助函数、reducer、资源、存储之间的分类。
- 三个模式中同一能力的接入位置、输入输出、数据归属和更新方式。
- 区分应用可观察的 Codex 事件、应用可强制执行的规则，以及 runtime 内部管理的推理和压缩。
- 每个教学结论对应的源码路径与函数／类名。
- 当前配置项、单位和计数语义。

不要把只在旧文档中出现的历史文件名，当作当前可点击的源码路径。
历史代码片段若没有实际历史源码支撑，要标注为“教学示意”或“依据版本记录重建”。
不声称每个历史版本都存在独立运行目录或可检出的提交。

## 4. 已确认的功能演进

| 版本 | 本次积木 | 主要学习内容 | 图结构要点 |
|---|---|---|---|
| V1 | 最小终端 ReAct | 消息、模型、工具、条件路由 | 模型与工具两个节点 |
| V2 | 三字段学习计划、JSON 存储与增删改查 | 工具 schema、校验、持久化业务数据 | 保留两个节点 |
| V3 | SQLite 与模块分层 | CRUD、事务、连接生命周期 | 存储变化，不新增业务图节点 |
| V4 | SQLite Checkpointer 与会话菜单 | thread_id、State 恢复、失败继续执行 | 检查点不是新图节点 |
| V5 | 摘要压缩与上下文管理 | 完整轮次、RemoveMessage、摘要注入 | 新增 summarize 节点 |
| V6 | 自定义 State 与工具历史 | Annotated、reducer、runtime、模型查询历史 | 历史处理在工具步骤内 |
| V7 | 工具中间件、HITL 与任务回放 | 包装顺序、interrupt、resume、@task | 保留三个节点 |
| V8 | 独立结构化待办草案 | JSON mode、Pydantic、业务校验、候选状态 | 新增 draft，形成四节点 |
| V9 | 次数限制与异常边界 | 配额、配对结果、SDK 重试、正常停止 | 四节点内部增加控制 |
| V10 | MCP | 协议、服务器、客户端、会话、工具包装 | 外部工具接入原工具路径 |
| V11 | Skills | 渐进式披露、名称状态、参考文件、上下文 | 复用模型和工具节点 |

早期业务叫“学习计划”，后来改成 Todo List Assistant。
历史阶段需要保留当时的术语，不把 Todo 能力倒填到最小版本。
当前 project 字段表示待办名称，字段名有意保留。

当前手动应用以 V11 为终点。create_agent 和 Codex SDK 在时间线外作为并列对照入口。
早期的流式交互计划未成为手动版的学习版本。Codex SDK 应用实际消费运行事件流，
展示 MCP 调用完成状态并收集最终回复，终端不逐 token 打印自然语言。

## 5. 网站的信息结构

至少提供以下五个互相联动的学习区域。可以使用页签或路由，不要求做成五个独立页面。

### A. 搭积木：版本演进

- 提供 V1–V11 时间线、上一版、下一版、跳转到最终版。
- 提供“加入下一块积木”操作，用动画展示新增连接和组件。
- 当前版新增、沿用、替换的组件要有清楚图例，不能只靠颜色区分。
- 同时展示本版目标、之前遇到的问题、接入位置和最小代码差异。
- 点击组件能看到职责、输入、输出、源码来源、相关概念。
- 可以比较两个版本，观察存储替换、State 增加和执行路径变化。
- 尚未出现的能力显示引入版本；不允许把后期能力默认为早期已有。
- 不需要实现可任意生成生产图的自由拖拽编辑器。
  如提供探索性拼装，应检查前置依赖，并标明它是教学组合。

### B. 最终版本架构

默认展示手动 V11 的整体架构，允许切换到 create_agent 和 Codex SDK 架构。
至少提供三个层级：

1. 全景：终端、模型、执行引擎、工具、存储、MCP 服务、技能文件。
2. 执行：手动图节点、框架 hook 或 SDK 会话轮次，以及各自的工具入口与审批位置。
3. 数据：消息、模型可见上下文、工具参数、业务数据和持久化位置。按模式展示图 State／任务缓存，或 Codex thread／应用工具作用域。

节点、工具、中间件、辅助函数、外部进程、运行资源和数据库必须使用不同标识。
不能把架构图中的每一个方框都叫作 LangGraph 节点。
主视图可以折叠细节；展开后必须能解释真实连接关系。

### C. 数据流实验室

选择一个场景，逐步执行并观察状态，不需要真实 LLM 或真实数据库。
同一操作应联动高亮执行图、可观察的消息／事件、对应模式的状态、存储和模型上下文。

### D. 三种实现的对照

- 先提供三列总览，比较“谁控制执行”“会话保存在哪里”“谁能拦截工具”等问题。
- 场景播放器默认对照手动图与 Codex SDK，可任意选择两种实现并排，不必把三张大图放在同一屏。
- 同一场景共用一份输入、初始待办和用户决定，各自产生执行轨迹。用“请求删除”“用户决定”“业务结果确认”等语义事件同步；某一侧缺少对应步骤时，标明原因。
- 对照结果区同时展示业务结果和执行差异。例如批准后都删掉一行，但旧图从中断处恢复，Codex 版则提交待审批操作并开启回执轮次。

### E. 知识点索引

提供可搜索的概念卡，并能跳转到对应演示、版本和源码。
每张卡至少包括：问题、职责、输入输出、数据流、常见误解、在适用实现中的位置。
对 `reducer`、`@task`、`TurnScope` 等模式特有概念标明适用范围。
避免把概念卡做成与交互场景无关联的术语字典。

## 6. “动态”的最低要求

动态不等于进场动画、hover 提示或会动的连线。
必须具有可改变、可回退、可解释的执行状态。

数据流播放器至少支持：

- 开始／暂停、上一步／下一步、重置。
- 点击事件时间线定位到某一步。
- 调整播放速度，自动播放可以随时暂停。
- 分支选择，例如批准／拒绝、合法／非法草案、成功／故障。
- 切换分支后正确清理旧分支状态，能够重新演示。
- 当前步骤说明：谁执行、收到什么、产生什么、接下来交给谁。

每一步至少能查看：

| 面板 | 应显示的内容 |
|---|---|
| 执行位置 | 当前组件、当前边、是否执行／跳过／等待／复用 |
| 消息／事件 | 图模式展示 HumanMessage、AIMessage、ToolMessage 与调用 ID；SDK 模式展示用户输入、SDK 可观察的轮次和工具事件、最终回复、可选的 ExternalMessage 回执 |
| 运行状态 | 图模式展示 State 更新前、增量和合并后；SDK 模式展示 thread ID、SDK turn 状态、工具作用域、待审批列表与操作结果 |
| 模型上下文 | 图模式展示合成请求中的提示词和消息；SDK 模式展示应用提供的输入、开发者指令、可观察的工具回执与技能输入，标注 runtime 内部上下文组装不可在本教学模拟中逐项核验 |
| 业务存储 | 教学用 Todo 数据在写入前后的变化 |
| 持久化 | 图模式展示已提交 State、待执行位置与适用的任务缓存；SDK 模式展示持久化 thread 和独立 SQLite，并标明进程内的待审批列表在退出时丢失 |
| 调用指标 | 图模式按代码展示模型调用、工具额度和适用的 HTTP 尝试数；SDK 模式展示 SDK turn、业务工具剩余额度、耗时及超时，不推算内部模型请求次数 |

默认展示易读摘要，允许展开原始 JSON 和代码。
没有发生变化的区域应显示“不变”或保持稳定，不能每一步都伪造更新。
只有真实的模型调用步骤才显示“本次模型输入”；其他步骤可以保留上一请求并标记为历史。
不要展示或伪造模型私有思维链。用可观察的工具请求、路由和简短教学解释描述 ReAct。

### 可修改的演示参数

至少允许修改：

- 待办名称、分钟数、日期或草案预算。
- 图模式的模型／工具调用上限和对应实现实际支持的摘要参数。
- SDK 模式的业务工具调用上限、轮次超时与草案超时。默认值从 `AppConfig` 核实。SDK 摘要阈值和精确模型次数控件显示为不适用。
- MCP 是否需要审批。
- 图模式的活跃技能上限；SDK 模式的技能控件用于比较普通输入和显式 `$skill-name` 输入。

这些是浏览器中的“演示参数”，不是对项目真实配置文件的修改。
历史版本尚无此能力时禁用控件并说明原因。
参数单位、合法范围及触发前提应清楚，不能只放无说明的滑块。

## 7. 必须实现的场景

以下是最小完整范围，不要只挑最容易的正常聊天完成。
所有场景使用明确标注的预设／合成数据，能重置、回退和重复播放。
下表沿用 LangGraph 的教学主线。Codex SDK 的对应轨迹见后表。

| 场景 | 必须观察到的行为 |
|---|---|
| 普通对话 | 新 HumanMessage、模型返回无 tool_calls 的 AIMessage、到 END |
| 多步计算 | 工具参数来自模型，ToolMessage 返回后用于下一次调用，最终结束 |
| 保存与查询待办 | 三字段校验、写入成功后的业务数据变化、下一次上下文刷新 |
| 查询工具历史 | 新记录如何产生、reducer 截断、查询自身不嵌套进历史 |
| 摘要压缩 | 触发条件、选择旧消息、摘要生成、移除旧消息、保留工具配对 |
| 删除批准／拒绝 | interrupt、暂停前没有删除、resume、批准执行或拒绝结果 |
| 中途退出并重启 | State 与任务结果恢复、连接重新建立、已完成任务复用 |
| 结构化草案 | 输入约束、独立 JSON 生成、结构／业务检查、候选与已保存数据分离 |
| 草案校验失败 | 旧候选清空时机、失败结果、没有新增保存记录 |
| 模型／工具超限 | 哪一步检查、哪些请求不执行、如何补齐结果并结束 |
| SDK 重试 | 临时 HTTP 故障后重试；HTTP 尝试数与成功模型调用计数不同 |
| MCP 调用 | 配置、发现、包装、审批、客户端发出请求、服务器执行、结果回流 |
| Skills 加载 | 元数据目录、load_skill、active_skills、下次模型上下文 |
| Skills 参考文件 | 活跃检查、隐藏 runtime、预加载映射、文本作为工具结果 |
| 同批多个工具的模式对照 | 手动顺序执行，create_agent 当前策略整批拒绝并引导逐个请求 |

三个实现至少共享普通对话、多步计算、保存与查询、删除审批、草案、重启、
工具上限、MCP 和 Skills 的业务场景。Codex SDK 轨迹增加以下观察点：

| 可操作场景 | 需要观察的 Codex SDK 数据流 |
|---|---|
| 打开会话并聊天 | 菜单列出、创建或恢复 thread。新会话在首轮开始后出现在保存列表。SDK turn 返回最终回复，终端继续等待输入。 |
| 删除：批准、拒绝、退出 | 首轮工具回执为待审批，SQLite 不变。首轮结束后终端询问。批准才执行，拒绝记录结果；退出并重启可恢复对话，未决定的请求不执行且需重新发起。 |
| 删除：预览后记录变化 | 在审批前修改模拟数据库中的分钟数，批准会返回“记录已变化或已移除”，用来演示按预览记录条件删除。 |
| 审批回执 | 在同一 thread 开启新 SDK turn，并发送 `ExternalMessage`。这轮的业务工具作用域保持关闭，额外业务调用被拒绝。 |
| 持久化和压缩 | 切换“退出并重启”，对照 thread、待办、草案、工具历史的保留情况。压缩展示 runtime 托管的概念边界，内部算法和触发时点不给出伪造轨迹。 |
| 草案：成功／超预算 | `generate_todo_draft` 先清理旧候选，单独的临时 thread 使用 `output_schema`。Schema 与按名称、日期、总时长的业务校验分开展示。成功更新候选，失败保持为空，两者都不改已保存待办。 |
| 工具额度与超时 | 每条终端用户输入打开新 `TurnScope`。请求进入时扣额，待审批／参数校验失败也计入。用尽后在副作用前拒绝。超时分支展示中断尝试、退出本次会话运行及未审批请求丢弃，保留已经提交的写入。 |
| 本地工具与上游 MCP | 比较本地 CRUD 和上游番茄钟两条路线。外部调用多一跳应用到上游服务；打开审批时，终端批准前，上游未收到调用。 |
| Skills 与工具观察 | 显式 `$study-plan` 生成 `TextInput` 和 `SkillInput`，后者在本轮提供技能正文；参考文件通过受限读取工具返回。工具事件和实际业务写入分开显示。 |

支持把相关步骤组合成完整故事，例如：

1. 提出学习安排目标。
2. 发现并激活 study-plan。
3. 查询指南、调用时间／计算工具（按场景需要）。
4. 生成未保存草案。
5. 后续明确要求保存。
6. 删除时审批。
7. 摘要后或重启后继续讨论。

也要能单独播放每个知识点，避免一个演示过长才看到重点。
对无法保证由真实模型按固定顺序选择的步骤，标注为“预设工具选择示意”。

## 8. 三种实现必须准确呈现的差异

| 能力 | 手动 LangGraph | create_agent | Codex SDK |
|---|---|---|---|
| 执行循环 | graph.py 明确注册四个节点与条件边 | agent.py 调用 create_agent 生成编译图 | 应用调用 SDK，Codex app-server runtime 执行模型和工具循环 |
| 固定依赖 | 节点构造函数与执行器闭包 | 工厂装配、中间件／工具构造函数与闭包 | main.py 装配 SDK、业务入口、SQLite 和上游 MCP 会话 |
| 动态基础上下文 | ModelNode.model | ContextMiddleware.wrap_model_call | 应用传入开发者指令、用户／技能输入；通过工具读取最新业务数据 |
| 会话持久化 | SQLite 检查点保存 AgentState | SQLite 检查点保存扩展 State | Codex 管理 thread；候选、待办与工具历史由应用另存 |
| 工具执行观察 | ToolNode 的包装函数链 | ToolExecutionMiddleware.wrap_tool_call | SDK 事件供展示；业务入口独立记录参数、结果与耗时 |
| 审批 | 自定义 approve_tool_call 与 interrupt | HumanInTheLoopMiddleware | 终端在首轮结束后处理 PendingCall，再发送执行回执 |
| 摘要 | 独立 summarize 节点，summary 字段，保留完整轮次 | 内置摘要中间件，摘要消息，保留近期消息组 | runtime 管理上下文压缩，应用没有旧版阈值及保留轮次控件 |
| 工具批次 | 普通工具按请求顺序逐个 @task 执行 | 当前额外策略只准入一个工具／模型响应 | 应用入口按收到的请求逐个串行处理，逐个检查额度 |
| 工具计数 | 整批完成后提交该批请求数；不是“一批只算一次工具” | 请求准入后、审批前占用额度，拒绝审批仍占用 | TurnScope 在入口扣额，待审批与无效参数也占额，解决同一待审批请求不再扣额 |
| 模型边界 | 主模型次数、图步数与重试分开 | 主模型次数、图步数与重试分开 | 有轮次时限和中断尝试，应用不控制精确的内部推理次数 |
| 历史记录 | ToolsNode 返回新增记录，reducer 合并 | before_model／after_agent 收集 ToolMessage 并去重 | Store 按 thread ID 保留近期执行结果；查询工具自身不写历史 |
| 草案请求 | 标记 ToolMessage.artifact，再路由到 DraftNode | 工具内独立生成，Command 更新，return_direct 结束循环 | 业务工具运行独立临时 thread，使用 output_schema 并做业务校验 |
| 草案展示 | DraftNode 产生一次最终 AIMessage | DraftPresentationMiddleware.after_agent 产生一次回答 | 通过工具回执给主会话，提示词指导模型展示一次未保存草案 |
| 技能激活和上下文 | artifact → ToolsNode → active_skills，ModelNode 注入正文 | Command 更新 active_skills，SkillsMiddleware 注入正文 | 显式 SkillInput 把正文交给 runtime；允许通过工具读取指定说明与参考文件 |
| MCP 资源 | McpConnections，元数据驱动原审批包装 | McpConnections，元数据参与内置 HITL 策略装配 | runtime 连接应用提供的本地 MCP；应用可作为客户端继续连接上游服务 |
| 模型与认证 | 当前使用 Groq | 当前使用 Groq | 使用 Codex 支持的模型；应用使用独立 Codex home 和本地配置 |

表格描述的是这三个项目的当前选择，解读时区分项目策略与框架能力。
手动 LangGraph 也能处理 Command；create_agent 本身并非只能执行一个工具。
不能把项目选择写成“主流唯一标准”。

### create_agent 中间件顺序实验

显示当前注册顺序，并区分三类规则：

- before_*：按注册顺序。
- after_*：反向顺序。
- wrap_*：较早者为外层，先进入、后退出。

不是所有中间件都实现每种 hook。
演示审批前配额准入、历史收集先于摘要，以及 Context 外层、Skills 内层。
可以提供“错误顺序”探索：交换 Context 和 Skills 后解释为什么指令可能被覆盖。
此探索只修改教学模型，不修改后端。

### 审批协议对照

从各自的 console.py、工具边界和测试核实三种审批协议，代码面板使用真实字段。

- 手动版本恢复值使用 approved 布尔值。
- create_agent 版本恢复值使用 decisions 中的 approve／reject 决策。
- Codex SDK 版本展示工具返回的 `pending_approval`、应用内 `PendingCall`、用户输入和 `ExternalMessage(tool_name="console_approval", ...)`。SDK 的运行权限与应用的删除审批分别标注。
- 示例可省略不相关字段，但必须标注“简化结构”。

### Codex SDK 的运行图与数据归属

以这张图为概览，播放器展开一条具体路径。蓝图上的 runtime 方框代表执行边界，
内部推理步骤仅显示 SDK 或测试能够观察到的事件。

~~~mermaid
flowchart LR
  U[终端输入] --> T[Python Codex SDK · Thread 与 Turn]
  T <-->|本地 app-server 协议| R[Codex runtime]
  R <--> L[模型]
  R --> C[(本应用的 Codex 会话目录)]
  R <-->|本机 Streamable HTTP MCP| G[业务 MCP 入口]
  G --> Q[TurnScope 配额与校验]
  Q --> B[本地业务工具]
  B <--> S[(应用 SQLite)]
  B --> D[临时草案 Thread · output_schema]
  Q --> P[PendingCall · 本轮进程内]
  P --> A[首轮结束后终端确认]
  A -->|批准本地删除| S
  A -->|批准上游调用| M[上游 MCP]
  Q -->|免审批的上游调用| M
  A -->|同一 Thread 的回执轮次| T
  R -->|工具与轮次完成事件| U
~~~

| 数据 | 所有者与生命周期 |
|---|---|
| 对话历史 | Codex 管理，thread 可重新列出和恢复，保存在本应用的 `data/codex_home/` |
| 已保存待办 | 应用的 `data/todos.sqlite`，同一应用内跨会话共享 |
| 候选草案、近期工具历史 | 同一个业务 SQLite 内按 thread ID 分隔，与对话压缩独立 |
| 业务工具额度、待审批请求 | 当前用户轮次的 `TurnScope` 和 `PendingCall`，退出后不从 thread 恢复 |
| 上游连接、私有 MCP 端点 | 应用运行资源，启动时建立，结束时清理 |

删除演示固定使用一条预设待办。让学习者在“工具调用已完成”事件处暂停，检查
数据库仍有该行，然后批准或拒绝，再观察实际结果。第一次 SDK turn 完成只说明
已返回待审批回执；回执 turn 用工具来源的 `ExternalMessage` 把真实结果交回会话。
该轮工具作用域关闭，不能添加新的业务副作用。超时或退出示例需分别保留已提交
的写入和丢弃未处理的审批请求。

## 9. 关键事实与常见误解

### 知识卡的最低覆盖范围

下列知识点要能从概念跳到真实代码，再跳到一个有输入／输出变化的演示。
基础语法采用简短展开卡，不必把每项做成独立长篇页面。

| 知识组 | 至少讲清楚什么 |
|---|---|
| 调用与返回 | 节点函数收到什么、返回什么，框架怎样使用返回值；普通辅助函数与路由函数不同 |
| 解包与合并 | 列表星号解包、字典解包只是 Python 构造数据；State 历史合并来自 reducer |
| 类型与校验 | TypedDict 描述字典结构，BaseModel 在被调用时进行运行时校验；类型注解不会自动校验所有业务数据 |
| 装饰器 | @tool 暴露契约、@task 缓存结果、@contextmanager 管理上下文，三者作用不同 |
| 资源生命周期 | with、yield、事务提交／回滚、closing、ExitStack，以及 MCP 会话如何关闭 |
| 依赖与会话 | 构造函数和闭包绑定固定依赖，State 保存会话数据；不要将已放弃的依赖传递方案展示成当前实现 |
| 配置与注入 | 普通工具参数、RunnableConfig 的 thread_id、框架注入的 ToolRuntime、共享 AgentConfig 各自来自哪里 |
| 消息与 State | 消息 ID、add_messages、增量更新、普通覆盖字段、自定义有界 reducer |
| 持久化与恢复 | 业务数据库、会话检查点、任务缓存、interrupt／resume 各保存什么 |
| 上下文与预算 | 历史消息、摘要、动态待办、技能正文与工具 schema，并不是同一份数据 |
| 结构化与自然语言 | JSON 格式、Pydantic、业务校验、模型最终普通回复的不同职责 |
| 执行边界 | recursion_limit、主模型调用次数、工具请求用量、HTTP 尝试次数是不同指标 |
| SDK 与 runtime | SDK 是应用调用 Codex 的接口，runtime 执行循环；Codex SDK 与 OpenAI Agents SDK 是不同工具 |
| Thread、Turn 与事件 | Thread 属于会话，一次 SDK Turn 可以包含若干工具请求，终端一次输入可以产生审批回执 Turn |
| 观察与拦截 | SDK 事件告知执行到了哪里，ToolGateway 在执行业务操作前实施配额、审批；记录完成事件无法替代门控 |
| 业务审批与运行权限 | 运行时权限配置决定可用的执行通道，终端的 y／n 决定当前业务操作是否提交 |

必须保留已经确认的设计取舍：

- 固定依赖采用构造函数／闭包，不为了统一形式再改回 partial 或自定义 Runtime.context。
- 普通回复不统一套固定输出模型，结构化能力集中在独立草案功能。
- 简单工具组装在 tools/__init__.py 合理，不为“看起来规范”新增 registry.py。
- 源码结构与控制流是两张不同的图，文件夹并不等于运行节点。

### ReAct、工具与执行

- 模型通过工具名称、描述和参数 schema 选择工具，Python 负责执行。
- 工具不是图节点，中间件也不必是额外图节点。
- END 结束一次图执行，不代表整个终端程序退出或清空会话。
- ToolRuntime 由框架注入，模型不负责传入隐藏的 runtime。
- Python 普通函数、@tool、图节点、@task、中间件需要明确区分。
- @task 的结果缓存与 asyncio 的异步通信任务不是同一概念。

### LangGraph 的 State、上下文与存储

- 节点通常返回增量更新，reducer 决定合并方式；不是每个字段都自动累加。
- messages、tool_history、active_skills 的合并规则与普通覆盖字段不同。
- State 中有的字段，不会自动全部发给模型；必须展示上下文组装步骤。
- model/client/connection/registry 等固定资源不进入检查点。
- tool_history 是近期有界记录，不等于完整执行审计。
- Checkpointer 和 thread_id 分别是持久化组件与会话标识。
- 两个 SQLite 文件分别保存图状态和三字段待办，不能合画成同一份记忆。
- Checkpointer 在执行中保存，break／exit 不是唯一的保存开关。
- 进程退出后的持久化来自 SQLite；不要把它和 InMemorySaver 混为一谈。
- summary 移除上下文消息，不代表删除旧检查点或压缩 SQLite 文件。
- 估算 token 阈值不保证第几轮触发，也不是整个请求的硬 token 上限。
  摘要还需要可压缩的完整旧消息；演示必须沿对应实现检查这些前提。

### 检查点回放的细节

手动版本的某次工具已经完成、后续工具正在审批时：

- 待办数据库可能已有变化。
- 已完成 @task 的结果可以已经持久化。
- 工具节点尚未返回，因此整批 messages／history／usage 更新可能尚未提交。

播放器必须分别显示业务副作用、任务结果缓存、已提交 State，不能伪造它们同时更新。
重启后要显示“复用缓存结果”，而不是再次执行、再次写入或重复增加计数。
仍然需要说明：数据库写入与检查点保存不是跨系统 exactly-once 事务。

### 结构化输出

- 普通聊天保持自然文本，不要求每次最终回答套统一 Pydantic 模型。
- 结构化输出仅用于有独立价值的草案步骤。
- JSON mode、Pydantic 类型校验、任务名／日期／预算业务检查要分开展示。
- 草案未保存，只有明确保存请求和成功工具结果才改变 Todo 数据。
- LangGraph 版本从上下文移除原始草案消息后，State 中的 todo_draft 仍可保留。
  Codex SDK 版本在独立 SQLite 按 thread ID 保存候选，通过工具查询。
- 保存草案里的待办不自动清空候选；新草案请求清除旧候选。
  三种实现的清除位置和输出路径不同，应沿当前源码展示。
- Codex SDK 的 `output_schema` 只用于临时草案 thread，Pydantic 及业务校验接在生成之后。

### MCP

- pomodoro 是真实可运行的演示 MCP 服务器，不是 mock。
- stdio 配置给出启动命令和参数；streamable HTTP 配置给出服务地址。
- 实际读取 mcp.json，mcp.example.json 只是模板。
- 两个 LangGraph 应用由 `McpConnections` 管理上游 `ClientSession`。
- Codex 版有两段协议连接：runtime 作为客户端调用本机业务 MCP；应用侧用 `ClientSession` 连接可选上游。MCP 服务注册、业务工具执行、上游转发是不同步骤。
- 模型看见的是工具契约；连接由相应的客户端和应用资源层管理。
- MCP 工具名称加服务器配置名的前缀；向服务器调用时使用原工具名。
- 默认审批开启，示例 pomodoro 显式关闭。演示时不要错误地假定它必然弹审批。
- 两个 LangGraph 应用通过后台事件循环承接异步 MCP SDK 调用。Codex 应用在自身异步资源作用域中托管业务端点及上游连接。
- stdio 使用 SDK 直接打开，避免环境值被 shell 二次展开。
- 两个 LangGraph 应用的后台循环有独立的关闭等待与清理过程。
- 服务器 isError 与传输故障按各实现的错误路径展示；Codex 入口转成适合模型读取的结果。不要模拟没有源码依据的重连、工具重试或上游写入回滚。

### Skills

两个 LangGraph 应用的自定义加载流程：

- Skills 是操作手册，不是另外创建一个 Agent。
- Python 在启动时预读文件，模型上下文按需披露；这两个“加载”不能混淆。
- 名称与描述默认可见，活跃技能正文后续注入，参考正文通过工具返回。
- active_skills 只保存激活名称，参考文本仍可能作为 ToolMessage 保存在消息中。
- read_skill_file 从预加载映射取值，不允许模型任意读取磁盘。
- 不能把“修改 system 上下文”和“把正文追加进聊天历史”混为一谈。
- Skills 不授权删除／保存，也不能绕过校验、审批或配额。
- 手动版本 load_skill 单独成批，避免同批读取尚未提交的激活 State。

Codex SDK 应用的流程：

- `prepare_workspace` 复制内置技能到应用工作目录的 `.agents/skills/`，
  `chat_input` 识别开头的 `$study-plan` 或 `$todo-cleanup` 并创建原生 `SkillInput`。
- 业务工具的受限读取是另一条路径，允许读取配套说明及指定参考文件。
  演示不用图模式的 `active_skills`、reducer 或活跃数量上限解释这条路径。
- 技能只提供工作流程，保存、删除和外部调用依然通过业务工具及审批检查。

## 10. 运行图与图例的要求

必须区分：

- 实线执行／调用边。
- 数据传递／State 更新边。
- 持久化与恢复边。
- 固定依赖或配置关系。
- 当前执行、待审批、已完成、复用、拒绝、故障。

可以使用 Mermaid 作为概览辅助，但核心播放器不能只有一张静态 Mermaid 图片。
可选择可交互 SVG、Canvas 或图组件实现联动高亮、选择和步骤定位。
需要文字说明和可访问的事件列表，不依赖动画或颜色才能理解。

手动最终版显示实际四节点图。
create_agent 图要明确区分“框架生成的执行结构”和“概念性中间件调用示意”。
如没有实际核实生成节点名称，标为概念视图，不伪造内部节点和数量。
Codex SDK 图要区分应用、SDK、runtime、工具网关和上游 MCP。用独立边型表达
runtime 事件、业务调用和审批回执；不要把 runtime 或网关标成 LangGraph 节点。

## 11. 前端内容与模拟器的组织

先检查仓库中是否已有可沿用的前端项目。
没有合适入口时，建议新建 web/todo-agent-learning/，与三个 Python 应用分离。
技术选择以易运行、易维护为准；可使用 React、TypeScript、Vite。
本任务默认不需要新增后端、登录、付费接口、线上部署或真实 LLM。

将内容／演示数据与 UI 分离，避免在组件里散落大量写死的解释和步骤。
建议的数据结构方向：

~~~ts
type ImplementationMode = "manual" | "create_agent" | "codex_sdk";

interface SourceRef {
  path: string;
  symbol?: string;
  line?: number;
}

interface LearningVersion {
  id: string;
  goals: string[];
  prerequisites: string[];
  addedComponentIds: string[];
  replacedComponentIds: string[];
  scenarioIds: string[];
  sources: SourceRef[];
}

interface TraceFrame {
  id: string;
  semanticPhase: string;
  activeComponentIds: string[];
  explanation: string;
  todoStore: unknown[];
  runtime: RuntimeFrame;
  sources: SourceRef[];
}

type RuntimeFrame =
  | {
      mode: "manual" | "create_agent";
      messages: unknown[];
      stateBefore: Record<string, unknown>;
      stateUpdate: Record<string, unknown>;
      stateAfter: Record<string, unknown>;
      modelInput?: unknown;
      checkpointView: unknown;
      taskCacheView?: unknown;
      metrics: Record<string, number>;
    }
  | {
      mode: "codex_sdk";
      threadId: string;
      turn?: { id: string; status: string; purpose: "user" | "approval_receipt" };
      events: unknown[];
      suppliedInput?: unknown;
      gateway: { open: boolean; remaining?: number; pending: unknown[] };
      savedThread: unknown;
      savedDraft?: unknown;
      savedToolHistory: unknown[];
      elapsedMs?: number;
    };
~~~

这些类型是设计起点，不要求照抄。需要根据实际场景细化。
模拟器应采用确定性事件／纯函数或可重放的不可变快照：

- 同一输入、参数和分支产生同一条轨迹。
- 上一步／重置恢复当前模式的消息或事件、状态、存储及指标。
- 不能仅移动高亮，而底部数据显示另一时刻。
- reducer 合并结果、预算边界和回放是否执行应可验证。
- 三种模式共享合成业务输入和语义阶段，保留各自的运行数据结构。
- 以删除为例，三个模式可共用 `delete_requested → waiting_for_user → decision_applied → outcome_visible`。
  这里的语义阶段只用于联动，不作为引擎事件名或对齐实际调用次数的依据。
- 数据量和 token 数若使用估算或演示值，清楚标注。

每个重要组件和阶段关联源码出处。
网页不能依赖任意本地文件路径在用户浏览器中自动打开；可以展示复制路径、
随构建整理的代码片段，以及已配置时才启用的仓库链接。
没有可用链接时不要放一个看似可点但无效的“打开源码”按钮。

## 12. 交互与视觉体验

希望得到的是有教学节奏的技术工作台：

- 以版本选择、执行图和步骤解释为主，少量稳定的视觉编码贯穿全站。
- 默认简洁，源码／原始数据／边界细节可展开。
- 组件名称与真实代码一致，同时提供易懂中文解释。
- 状态变化有清楚的前后对比，当前事件不会被自动滚动藏起来。
- 对照模式可以清楚看出相同结果是通过不同流程产生的。
- 桌面允许从三种实现中任选两个并排。窄屏保留当前语义步骤，切换标签时共享场景与参数。
- 播放、审批选择、节点选择和面板切换支持键盘操作。
- 尊重减少动画设置；动画关闭后仍能完整学习。
- URL 或本地 UI 状态可保留版本／场景选择，不存储任何个人凭据或真实业务数据。

不要求某种固定品牌风格。不要为炫技牺牲文本可读性与数据流准确性。

## 13. 范围与数据隔离

后续开发仅新增学习网站及必要的配套文档。
除非用户另行要求，不修改三个 Python 应用的运行逻辑来配合展示。
允许为核实行为使用已有离线测试或独立临时脚本。

网站默认是基于真实源码的交互教学模拟：

- 清楚标注合成对话、预设模型选择、模拟存储、模拟检查点和 SDK 示例事件。
- 不读取真实 .env、个人 mcp.json、data/ 或聊天数据库。
- 不读取用户的 Codex home、登录凭据或原始会话日志。网页播放器使用本地合成事件，不要求启动 Codex SDK、app-server 或业务 MCP 端点。
- 不在浏览器打包真实 API key、私有 URL 或个人日志。
- 不启动个人配置中的 MCP 服务器，不使用真实模型费用作为演示依赖。
- 用户未明确要求时，不加入真实 API 调用、生产后台、联网会话回放或部署。
- 若要引用本地服务器验证结果，用临时／公开示例配置并准确说明验证范围。

## 14. 执行顺序与完成标准

按下面顺序推进，不停留在“可以这样做”的建议：

1. 阅读规则、版本文档与源码，整理事实清单和来源映射。
2. 确定信息架构和版本／组件／场景数据模型。
3. 完成 V1→V11 搭建导航及最终架构浏览。
4. 完成可回退播放器与各自的运行状态、上下文和持久化面板。
5. 完成三种实现的共用场景和特有分支，包含 Codex 的审批回执轮次与重启行为。
6. 完成三列总览、任选两种实现的语义对照和中间件顺序演示。
7. 补齐概念索引、源码出处、运行说明和验证。
8. 实际启动网站，在浏览器逐项操作，修复发现的问题。

除非缺少必要源码或遇到明确阻塞，合理决定常规实现细节并继续完成。
不能以首屏好看或正常路径能播放作为整个任务完成的依据。

### 必须通过的验收

- [ ] V1–V11 全部可选择，新增积木和前置依赖解释准确。
- [ ] 历史节点数量与最终四节点结构正确。
- [ ] 三种架构均可切换，V11 后有两个并列对照入口。三列总览和任选两种实现的语义同步可实际操作。
- [ ] 普通对话、多步工具调用都可以播放、回退、重置。
- [ ] 修改演示参数会改变轨迹，而不是只改变标签。
- [ ] 审批前没有发生删除，拒绝后没有执行副作用。
- [ ] 重启时能区分图 State、任务结果缓存、Codex thread、业务数据及进程内待审批请求。
- [ ] 图模式的摘要演示保留工具请求／结果配对。Codex 模式清楚标注托管式压缩和可观察边界。
- [ ] 草案未自动写入已保存待办；错误候选不会被当作成功。
- [ ] 三种 Skills 路径可切换。Codex 显式 SkillInput、受限参考文件和图模式的 active_skills 各自能定位到源码。
- [ ] MCP Client／Server、启动／调用、stdio／HTTP、资源／检查点区分正确。
- [ ] Codex 图清楚展示 runtime 调用本地业务 MCP，及应用可选转发到上游的两段协议。未批准的上游请求不会发出。
- [ ] 手动批次和 create_agent 单工具策略的差异可实际观察。
- [ ] Codex 删除轨迹区分工具完成事件、待审批回执、终端结果和下一次 SDK turn。回执轮次无法引入新的业务操作。
- [ ] Codex 的批准、拒绝、记录变化、退出、超时和额度耗尽轨迹都有可验证的数据变化。
- [ ] 计数器显示真实项目语义。Groq HTTP 重试与成功模型调用分开，Codex 的 SDK turn 与内部模型次数分开。
- [ ] create_agent 的 before／after／wrap 顺序演示准确。
- [ ] 关键知识点均能跳到相关场景和源码来源。
- [ ] 没有用占位按钮或“后续再实现”替代核心功能。
- [ ] 构建、适用的 lint／类型检查和模拟器核心测试通过。
- [ ] 浏览器中实际检查主要分支，控制台没有未处理错误。
- [ ] 运行说明明确，不要求读取个人配置或真实 API key。

测试应关注模拟器的实质行为，例如 reducer、分支重置、恢复不重复执行、
配额拒绝无副作用、Codex 回执轮次拦截、退出丢弃待审批请求及三种模式的语义对照。
如工具条件不允许浏览器验证，应准确报告未验证项，不能宣称已经检查。

### 最终交付说明

交付时提供：

1. 网站项目位置与启动／构建命令。
2. 主要区域、版本范围和可运行场景列表。
3. 一条推荐体验路径：从 V1 搭到 V11，再用相同的待办删除场景对照 create_agent 和 Codex SDK。
4. 如何找到各模式的状态、模型可见数据、持久化和源码面板。
5. 实际执行的验证与发现的限制。

本文件的目标是让另一个 Agent 不仅知道这些功能“是什么”，还知道怎样把
真实的搭建过程、执行顺序和数据变化变成可以亲手探索的学习体验。
