# 待办清单助手 Agent

[English](README.md) | 简体中文

这是基于 LangGraph 的终端待办助手，包含七个本地工具、四个图节点、滚动对话摘要、
SQLite 会话检查点、待办数据库，以及通过自定义 State reducer 保留的近期工具执行记录（默认十条）。
每条待办仅使用 `project`（名称）、`minutes`（预计耗时）、`date`（安排日期）三个字段。

代码注释、提示词、工具说明与终端文案使用英文；助手默认用英文回答，用户明确要求时可以使用其他语言。
本文说明当前用法与设计；学习路线与功能演进统一记录在 [学习路线](docs/VERSIONS.zh-CN.md)。

| 工具 | 用途 |
|---|---|
| `get_current_time` | 获取电脑本地日期和时间 |
| `calculate` | 加、减、乘、除运算 |
| `save_todo` | 新增待办，或更新同名同日期待办的预计耗时 |
| `delete_todo` | 人工批准后，按名称和安排日期删除指定待办 |
| `list_todos` | 查询待办，可按精确名称／日期筛选 |
| `generate_todo_draft` | 为指定任务、日期和总时长预算请求一份未保存草案 |
| `get_tool_history` | 读取当前会话保留的近期工具执行 |

## 待办字段与存储

待办跨重启保存，由本应用的会话共享。每个会话分别保存自己的消息、摘要和工具执行记录。

| 存储字段 | 待办含义 |
|---|---|
| `project` | 待办名称 |
| `minutes` | 预计耗时，1～1440 的整数分钟 |
| `date` | 安排日期，格式为 `YYYY-MM-DD` |

保存仍需要三个字段。保存工具要求 `minutes` 是真正的整数，
布尔值、数字字符串和浮点数会被拒绝，不自动转换。当前没有完成状态，表达“做完了”不会自动删除，也不能标记完成。同名同日期更新只改变耗时；修改名称或日期会新增记录，不会替换旧记录。

待办使用 `data/todos.sqlite` 数据库、`todos` 表和 `TodoItem` 类型。`agent/memory.py` 中的存储函数为 `load_todos()`、`save_todo()`、`delete_todo()`；`agent/tools/` 中提供给模型的工具为 `save_todo` 和 `delete_todo`。会话与摘要使用 `data/todo_checkpoints.sqlite`。

## 启动

模型配置统一放在这个 Agent 自己的 `src/agent_apps/todo_list_assistant_agent/.env`，位于应用根目录，与 `config/` 目录同级。如果文件不存在，复制旁边的 [`.env.example`](.env.example) 为 `.env`，再填写密钥：

```dotenv
GROQ_API_KEY=填写你的密钥
AGENT_MODEL=openai/gpt-oss-20b
GROQ_BASE_URL=https://api.groq.com
```

在项目根目录运行：

```bash
uv run todo-list-assistant-agent
```

每次启动都会先进入会话列表：

```text
Conversations
1. home-todos
2. work-todos
0. New conversation
Type 'exit' to quit.
Choose a conversation:
```

输入已有会话的编号即可继续；输入 `0` 并填写名称即可新建。新会话在发送第一条消息后保存，未发送消息就退出不会产生历史条目。首次启动列表为空，查看菜单和退出不需要 API Key。

如果已经激活并安装了项目的虚拟环境，也可以运行：

```bash
python -m agent_apps.todo_list_assistant_agent
```

模块入口也进入同一个菜单。会话名称作为内部 `thread_id`，区分大小写，首尾空白会被移除；新建时拒绝空名称和已有名称。检查点数据库中的会话在重启后仍可选择，启动时由菜单选择会话，不支持命令行指定会话。

输入 `exit` 或 `quit`（不区分大小写），或按下键盘中断组合键结束。配置只读取 Agent 自己的 `.env`，不受启动目录影响，不使用外层仓库 `.env` 或 shell 中的同名变量。读取不会修改全局 `os.environ`，也不展开 `${...}` 引用。真实 `.env` 已被 Git 忽略，`.env.example` 是可提交的配置模板。

终端使用 Python 标准库 `readline` 处理中文字符的退格和编辑，不自动记录输入历史。当前运行环境为 macOS；不需要额外安装终端输入依赖。

## 先体验三种对话

普通交流，不需要工具：

```text
你：你好，帮我安排日常事务。
助手：……
```

使用工具，可能需要多步计算：

```text
你：7 件事情，每件预计 45 分钟，一共多少小时？请分步计算。
Tool: Calculating 45.0 multiply 7.0.
Tool: Calculating 315.0 divide 60.0.
Assistant: That is 315 minutes, or 5.25 hours.
```

上面是预期的过程示例，实际回复及工具调用顺序由模型决定。

计算器的 `operation` 参数使用 `add`、`subtract`、`multiply`、`divide`，时间工具返回本地时间，格式为 `YYYY-MM-DD HH:MM:SS`。

理解会话历史：

```text
你：我每天有 30 分钟处理家务。
助手：……
你：按我刚才说的时间，一周能安排多少小时？
助手：……
```

也可以询问“现在几点了？”，观察时间工具的调用。

## 按积木阅读

1. 读 `agent/tools/`：普通函数怎样通过 `@tool` 变成工具；参数和说明怎样帮助模型选择工具。
2. 读 `config/` 和 `agent/model.py`：配置与模型创建；再看 `agent/graph.py` 怎样一次性组装模型包装器与节点对象。
3. 读 `agent/memory.py` 和 `agent/prompts.py`：待办事项怎样写入数据库、查询，再进入系统提示词。
4. 读 `agent/middleware/`：理解 `ToolNode` 怎样在每次工具调用周围传入请求与执行器。
5. 读 `agent/state.py` 和 `agent/nodes/tools.py`：`tools()` 怎样返回新增记录，reducer 怎样合并；再读 `agent/nodes/model.py`、`agent/nodes/summarize.py` 的模型调用与摘要检查，最后看 `agent/graph.py` 的组装和路由。
6. 读 `agent/checkpoints.py` 和 `console.py`：存储层怎样返回会话名称列表，菜单怎样选择，以及 `chat()` 怎样将新消息和对应的 `thread_id` 交给图。
7. 读 `agent/schemas.py` 和 `agent/nodes/draft.py`：模型结构化输出、请求约束检查、草案持久化和单条最终回复。
8. 最后看 `main()` 和 `__main__.py`：启动过程以及 `SqliteSaver` 的连接生命周期。

核心流程如下：

```text
用户输入 → 摘要检查 → 模型节点
             ├─ 普通工具调用 → 工具节点 → 回到模型节点
             ├─ 草案请求 → 工具节点 → 草案节点 → END
             └─ 自然文本回复 → END → 本轮结束 → 等待下一次输入
```

`bind_tools()` 让模型知道工具的名称、参数和用途；模型返回的是调用请求，真正执行工具的是 `ToolNode`。工具结果以消息形式返回给模型，用于继续判断。

模型通常可以根据对话选择工具，但不保证每次都遵循提示词。观察程序实际打印的工具提示，可以确认是否执行了工具；程序不会展示模型的内部推理。

## 对话历史持久化

运行 `uv run todo-list-assistant-agent`，选择 `0`，命名为 `home-todos`，告诉助手“我想整理日常事务”，然后退出。再次启动，按列表中显示的编号选择 `home-todos`，询问“我刚才想整理什么？”。图会根据该会话的 `thread_id` 从 `data/todo_checkpoints.sqlite` 恢复消息。

新建 `work-todos` 会使用另一段独立的历史。每次启动都由菜单选择，不需要记住或传入 ID。编号只是本次菜单的位置，会话名称才是数据库中稳定的标识。

终端每轮传入新的 `HumanMessage` 并重置两个用量计数。`AgentState` 在 `MessagesState` 基础上声明可选的 `summary`、`tool_history`、`todo_draft`、`model_calls_this_turn` 和 `tool_calls_this_turn` 字段，Checkpointer 将它们与近期用户消息、模型回复、工具请求和工具结果一起保存。

## 生成待办安排草案

例如输入："Propose durations for Python and English on 2026-11-09,
within 90 minutes total. Show a draft without saving it."

模型单独调用 `generate_todo_draft(projects, date, max_minutes)`。工具校验请求，
用内部 artifact 返回普通约束数据；图转到 `DraftNode.draft`，使用同一个配置好的基础模型，
调用 `with_structured_output(TodoDraft, method="json_mode", include_raw=True)`。
只有草案分支请求 JSON，普通聊天保持自然回复。供应商需要支持 JSON object mode；
提示词提供 schema，Pydantic 在本地校验字段，不要求供应商强制执行严格 JSON Schema。

TodoDraft 包含非空的 TodoView 列表，每条仍只有 project、minutes、date。
先检查严格类型、额外字段、非空名称、真实规范日期，以及 1～1440 的整数分钟数；
再由 Python 检查指定任务是否各出现一次、日期是否一致、总分钟数是否超过请求预算。
名称必须唯一且没有首尾空格，预算为 1～1440 分钟，至少给每个任务留出一分钟。
结构／解析失败、模型回复不完整或业务规则不通过时，只说明失败，不保留有效草案，也不写入待办。
草案失败文案只描述生成步骤，同一轮之前已成功保存的待办继续保留。
图中没有自动修正重试步骤；API 错误沿用终端错误处理，可恢复到草案节点。
模型 SDK 已有的网络重试设置仍然生效。

已接受请求的约束与模型生成的时长分开保存。外层模型从对话提取约束，能否准确理解
用户要求仍依赖模型；生成模型只接收这些约束，无权修改检查标准。
当前只为单个日期的任务建议时长，不校验固定的逐项时长、多日期、优先级、开始时间，
也不检测与已保存待办的冲突；缺少或超出支持范围的要求应先澄清。

以下是示意输出，草案固定标签目前使用英文，任务名称原样保留：

```text
Assistant: Todo draft for 2026-11-09:
- Python: 50 minutes
- English: 30 minutes
Total: 80 / 90 minutes.
Not saved. Ask to save this draft if you want to keep it.
```

校验通过后，代码格式化一条普通 AIMessage，直接进入 END，不单独打印内部结构化数据，
也不再调用另一个 LLM 复述。终端只打印最终助手消息。
`list_todos` 是普通只读 JSON 文本查询，可按精确名称／日期筛选；结果交给模型组织最终回答，
终端没有额外的列表展示器或查询结果重放面板。

最新有效草案以普通数据保存在会话的 `AgentState.todo_draft`，随检查点持久化，
重启和摘要后仍可用，并与当前已保存待办分别提供给下一次模型调用。
新的草案请求会在生成前清空旧候选，替换失败不保留可用旧草案；
后续模型提示词会明确说明当前没有有效草案，即使历史消息中仍保留旧候选。
生成草案不会新增或修改待办记录；用户之后明确要求保存时，逐条调用 `save_todo`。
是否暂停审批由 `AgentConfig.approval_tools` 决定，默认只有删除需要审批。
每条保存是独立事务，可能部分成功。保存后草案仍是建议快照，实际保存情况以工具确认和当前数据库为准。

草案请求必须单独调用；与其他工具混在同一批时，整批在副作用发生前拒绝，
每个调用都有对应错误结果。普通工具仍使用观察、可配置审批和检查点任务。
工具历史记录的是草案请求工具的结果，生成／检查结果位于 State 和消息中。
既有待办、聊天消息和数据路径保留。

## 每轮模型与工具次数限制

在 `config/agent.py` 修改 `AgentConfig.max_model_calls_per_turn`（默认 6）和
`max_tool_calls_per_turn`（默认 8）后重启。图仍只有四个节点，检查直接写在现有 model／tools 方法中。

模型节点调用 ReAct 主模型前检查 `model_calls_this_turn`，调用成功后才返回加一的总数。
达到上限就返回一条固定 AIMessage，现有路由直接进入 END，不额外调用模型。
摘要生成和结构化草案模型不计入这个模型计数。这是已完成调用次数限制，
不是 HTTP 尝试、token、耗时或费用上限；节点返回前的失败和 SDK 内部重试不会增加计数。

工具节点执行任务或发起审批前检查整批请求。额度内的批次在节点完成时按单个请求计数，
包括已处理错误、人工拒绝、非法混合草案批次和历史查询；历史查询依然不生成工具历史记录。
整批超过剩余额度就全部拒绝，不增加用量。为每个请求补齐一条错误 ToolMessage，
再由代码返回一条最终回复，工具路由进入 END。拒绝结果计入工具历史，历史查询除外。
之前保存的待办和已完成结果保留；被拒绝的新草案请求会清空旧候选，与其他替换失败保持一致。

终端每次收到非空新用户消息时，把两个计数一起设为零。审批和失败恢复不传计数，
保留检查点中的用量。工具批次暂停时尚未返回计数；恢复后复用已完成的 @task 结果，
整批节点完成时只统计一次。计数按会话保存，不放在节点实例属性中。
直接调用图时，新轮次必须像下方示例一样显式传入两个零；单独传入新 HumanMessage 不会自动重置。
旧检查点缺少字段时按零处理，无需迁移。

正常达到次数上限只结束当前轮，终端仍可继续接受输入。`recursion_limit=20` 保留为独立的图步数兜底；
把它调得太低仍可能触发 GraphRecursionError 并结束终端会话。
不新增预算、额度预留、准备或结束节点。

## 异常分类与模型 SDK 重试

不同错误交给不同层处理：已知输入错误变成可修正的工具结果，存储失败停止当前运行，
未标记的程序错误保留 traceback。

| 类别 | 行为 |
|---|---|
| 工具参数／schema 错误 | ToolInvocationError 或 Pydantic ValidationError 转为带字段原因的错误 ToolMessage |
| 明确的值／类型校验 | InputValueError／InputTypeError 转为带具体原因的错误 ToolMessage |
| 计算器非有限数、除数为零、溢出 | 抛出 InputValueError，协议状态为 error，不再作为成功文本返回 |
| 磁盘或 SQLite 失败 | 向外传播到终端，保留已提交工作，停止且不自动重试工具 |
| 未标记的 ValueError、TypeError、RuntimeError 等程序错误 | 保留 traceback，不伪装成参数问题 |
| HITL 控制信号 | 继续抛给 LangGraph，不把审批暂停当作可重试失败 |

`agent/errors.py` 的两个小型校验异常分别继承 ValueError 和 TypeError，
直接 Python 调用方仍可捕获相应的内置类型。存储校验和工具的明确检查使用这些标记，
schema 校验器继续由 Pydantic 包装；handle_tool_error 只格式化这些已知输入错误。
保存工具在入口使用 Pydantic StrictInt，避免自动转换绕过存储类型检查。
模型修正参数后再次调用是一个新请求，继续占用工具次数。专用草案节点保留原有结构／业务拒绝处理。

模型 HTTP 请求只由 Groq SDK 重试。`config/model.py` 的 `ModelConfig.max_retries=1`
表示首次尝试后最多重试一次，合计最多两次。ReAct、摘要和草案共用配置好的客户端，
不叠加节点、@task 或工具中间件的重试策略。当前安装的 SDK 通常会重试连接／超时、
HTTP 408／409／429 和服务端错误，自行处理退避及支持的 Retry-After／服务端提示；
没有服务端重试覆盖提示时，常见 400／401／403／404／422 不重试。
HTTP 200 后的结构化解析失败不是 SDK 网络失败，不会自动再生成一遍草案。

终端分别说明认证、权限、模型／端点不存在、请求格式、限流／配额、超时、连接与服务端错误，
并保留供应商详情。终端不发起额外 HTTP 重试。修改模型重试设置后重启生效，agent 本地 .env 字段不变。

SDK 重试后成功，model_calls_this_turn 只增加一次；全部失败时节点不返回计数更新。
工具不自动重试，即使磁盘错误可能只是暂时故障。之后明确重启／恢复时，可以复用已保存的任务结果，
但这不消除外部写入与检查点之间的事务窗口，不能理解为严格只写一次或自动回滚。

## 滚动对话摘要

每个新用户轮次第一次调用模型之前，摘要节点估算“已有摘要＋消息历史”的 token 数。达到配置阈值后，用“旧摘要＋较早的完整对话”生成新摘要，原样保留最近 **2 个完整用户轮次＋当前轮**。一轮包含工具请求、工具结果和最终回答，并不是一条消息。

修改 `config/agent.py` 的 `AgentConfig` 后重启。Agent 参数直接写在 Python 中，
`.env` 只保存模型配置；下面六个数值参数都应使用正整数，
`approval_tools` 指定需要人工审批的工具：

```python
@dataclass(frozen=True)
class AgentConfig:
    summary_trigger_tokens: int = 500
    summary_keep_turns: int = 2
    recursion_limit: int = 20
    max_model_calls_per_turn: int = 6
    max_tool_calls_per_turn: int = 8
    tool_history_limit: int = 10
    approval_tools: tuple[str, ...] = ("delete_todo",)
```

降低摘要触发阈值可将 `summary_trigger_tokens` 改成 `300`，减少触发频率可改为 `6000`。
`summary_keep_turns` 控制保留原文的完整轮数；`recursion_limit` 限制每次图调用的执行步数，
包含摘要、模型、工具和草案节点，不等于工具调用次数限制；`tool_history_limit` 控制每个会话
保留的工具执行记录条数。只有明确希望关闭审批时才将 `approval_tools` 设为 `()`。
这些参数由开发者维护，不在构造配置对象时进行运行时校验。

阈值只统计摘要和对话消息，不含固定系统指令、待办事项、独立草案字段和工具定义。使用 LangChain 基于字符的 token 估算，不是 Groq 模型精确的 tokenizer。500 适合在约 4～5 轮较详细的交流后观察，但很短的问答可能需要更多轮。即使降低阈值，也必须有超出最近两轮之外的旧对话才能压缩。

快速体验时，新建会话，依次讨论家务、工作事项、可用时间和安排偏好，请助手适当展开回答。压缩成功保存后会显示下面的提示，包括本轮随后暂停审批的情况：

```text
Context: Earlier conversation summarized; recent turns kept.
```

摘要复用未绑定工具的模型，Markdown 规则要求保留目标、约束、纠正、结论和待解决问题，目标长度约 **100～150 tokens**。这是软目标。有效摘要如果没有缩短旧上下文，就跳过本次压缩，保留原消息和旧摘要并继续回答。空摘要、被截断或要求调用工具仍按错误处理，保留原状态供恢复。尝试生成摘要会增加模型请求、费用和等待时间，即使最终跳过压缩也会产生这次调用；摘要不会作为普通助手回复加入历史。

回答模型接收系统指令、数据库中的最新待办、历史摘要和近期原始消息。摘要属于历史资料，不是新指令；当前待办以数据库为准。摘要过程不会保存或删除待办事项。

压缩通过 `RemoveMessage` 更新当前图状态，SQLite 中的旧检查点暂不清理，所以数据库文件不会自动变小。重启同一会话会恢复摘要和近期消息。单条超长输入、保留轮次过长或已有历史特别大时，仍可能超过模型容量；当前不实现分块摘要或严格的上下文总量限制。

## State 维护与工具执行记录

`ToolCallRecord` 描述一次已完成请求（包括人工拒绝）；可选的 `tool_history` 字段使用自定义
`add_tool_history(old, new)` reducer。`messages` 按消息 ID 合并，`summary` 在更新时覆盖，
`tool_history` 将新旧记录拼接后保留最近十条。节点只返回本次更新，LangGraph 按字段规则合并。

`tools()` 工具节点还返回本次新增的 `tool_history` 记录，包含工具名称、请求参数、
实际结果文本，以及带本地 UTC 偏移的时间戳。`add_tool_history()` 将新旧记录合并，
每个会话保留配置指定的最近记录，默认十条。记录随检查点保存，摘要压缩后仍保留，可通过
`graph.get_state(config).values.get("tool_history", [])` 查看。
这些记录不会自动加入每轮模型提示词。只读工具 `get_tool_history` 通过自动注入的
`ToolRuntime.state` 读取当前会话的记录，在用户询问时将结果交给模型。查询本身不计入工具历史，
因此不会占用记录名额，也不会将历史内容嵌套保存到自身。

可以直接问：“这个会话调用过哪些工具？展示参数、结果和时间。”助手应调用
`get_tool_history` 并展示保留的近期执行记录（默认最多十条）；空列表表示没有记录可展示。该工具不需要模型提供参数，
读取的是本批工具执行前的状态；要包含另一工具的新执行，需要在后续步骤查询。
没有新增独立的终端命令或自动展示面板。

图为四个节点、七个工具。工具历史使用已有检查点数据库，没有独立的表；
保留条数由 `AgentConfig.tool_history_limit` 配置，默认十条；
`tools()` 包装 `ToolNode` 来生成记录。图的 `recursion_limit` 默认是 `20`，
同时受前述已完成调用次数限制。工具历史由节点生成；下面的观察中间件负责向终端输出执行信息。

调小 `tool_history_limit` 后，新上限在下一次工具节点更新合并时生效。
恢复检查点本身不会执行 reducer，因此此前保存的记录可能暂时超过新上限，
第一次查询工具历史时也可能返回这份旧列表。

## 人工审批与工具观察

删除操作默认需要人工批准。模型请求 `delete_todo` 时，`approve_tool_call()`
先调用 `interrupt()`，工具此时尚未执行。图保存待处理工作，终端展示工具名、调用 ID 和参数：

```text
Human approval required
Tool: delete_todo
Call ID: delete-1
Arguments:
{
  "project": "Clean room",
  "date": "2026-11-06"
}
Approve this call? [y/n/exit]:
```

输入 `y`／`yes` 批准，`n`／`no` 拒绝，`exit`／`quit` 保留待审批请求并退出。
选项忽略大小写及两端空格，空输入或未知内容会重新询问。Ctrl+C／Ctrl+D 同样退出，
不会批准请求。重启后选择原会话，先审查已保存请求，再接受新的聊天输入。
存在待处理工作时，应保持审批配置与任务顺序稳定。
拒绝时返回明确说明未执行的错误 `ToolMessage`，模型据此解释结果；不会删除待办，
也不自动结束整个图。提示词要求模型没有新的用户请求时不要重试被拒绝操作，
这是模型行为指引，不是永久禁用工具。

`console.py` 将待审批与普通失败任务区分处理：审批通过相同的 `thread_id` 和
`Command(resume={interrupt_id: {"approved": True}})` 恢复（拒绝使用 `False`）；
普通失败仍使用 `invoke(None, config)`。审批答案不会作为 `HumanMessage` 加入聊天，
图暂停时也不会打印最终助手回答。多个受保护调用按请求顺序逐一审批，不支持编辑参数或批量批准。

`agent/middleware/approval.py` 定义 `approve_tool_call()`；
`agent/middleware/tool_execution.py` 包含 `observe_tool_call()` 与 `handle_tool_error()`。
`middleware/__init__.py` 统一导出这些 hook，并定义 `tool_call_middleware()` 组合两个包装函数：

```text
工具请求 -> approve_tool_call（外层）
              |-- 批准／无需审批
              |      -> observe_tool_call（观察）-> execute(request)
              |      <- 返回结果并输出耗时
              |-- 拒绝 -> 错误 ToolMessage，不执行工具
```

`ToolNode` 接收 `wrap_tool_call=tool_call_middleware`，左侧是构造参数名，
右侧函数把审批放在观察外层。`observe_tool_call(request, execute)` 负责观察。
只有获准执行时才进入观察，所以计时不包含人工等待，拒绝请求没有工具执行观察日志。
观察函数的 `finally` 输出返回协议状态或向外传播的异常，不从内容推断业务成功。
计算器校验现在抛出输入错误，由 ToolNode 返回 `error` 状态；包装函数原样透传 `Command`。

`handle_tool_error()` 将审批暂停等图控制信号继续向外抛出；已知输入错误包含具体原因，存储失败和未标记程序错误继续向外传播。
中间件不注册成工具，不依赖提示词才能运行。图执行路径上的审批请求与决定由代码处理；
直接从 Python 调用存储函数或工具对象，不经过这层中间件。

### 单次工具调用的检查点

`tools()` 按顺序执行同批请求，每次调用放进 `execute_tool()` 检查点任务（`@task`），
保存完成后的 `ToolMessage`。恢复审批会重跑工具节点，但已完成的任务直接返回保存的结果。
例如先保存待办、后暂停在删除审批时，重开会话批准删除，不会重新执行前面的保存。

任务与中间件函数不是额外图节点，图包含摘要、模型、工具、草案四个节点和七个工具。
每个工具读取本批开始前的 State；要在查询中包含本批记录，需要在后续模型步骤查询。
整批完成后，`tools()` 才返回消息与新增历史记录。暂停期间，前面工具可能已提交业务修改，
但本批消息／历史增量还没有返回。

观察日志仅输出到终端，不成为模型消息或检查点字段。已解决的拒绝请求会在 `tool_history`
记录拒绝文本；仍待审批的请求尚无结果记录，历史查询本身继续排除。
可恢复的审批需要 Checkpointer，终端入口已经提供原有 `SqliteSaver`，不需要迁移数据库或增加业务字段。
工具副作用与检查点写入仍属独立事务：若业务提交后、任务结果保存前进程崩溃，仍可能重新执行。
复用已完成任务不等于严格的恰好执行一次保证。

## SQLite 待办事项存储

```text
输入：添加待办：2026年11月4日，整理房间，预计30分钟。
Tool: Saved todo: 整理房间, estimated 30 minutes, scheduled for 2026-11-04.
助手：……
You: exit
```

重新启动后，询问“我有哪些待办事项？”。每次调用模型前会从 `data/todos.sqlite` 查询全部待办，并加入系统提示词，因此不需要重新提供名称、预计耗时和日期。

数据库的 `todos` 表只有 `project`、`minutes`、`date` 三个业务字段，以待办名称和安排日期组成联合主键。查询后仍返回原来的字典列表，供提示词展示，例如：

```json
[
  {"project": "整理房间", "minutes": 30, "date": "2026-11-04"},
  {"project": "审阅代码", "minutes": 45, "date": "2026-11-04"}
]
```

预计耗时以整数分钟保存，范围为1到1440；日期必须是 `YYYY-MM-DD` 格式的真实日期。名称、预计耗时、日期缺少任意一个时，助手应先询问。遇到“今天”“明天”等相对日期时，先通过时间工具确认；小时数先换算为分钟。

同一名称、同一日期再次保存时更新预计耗时；不同名称或日期会新增待办，其他记录保留。普通交流和临时计算不自动保存。例如“把2026年11月4日的整理房间待办更新为45分钟”，只更新对应的一条。

第一次查询或写入时自动创建数据库，路径由 `config.DATA_DIR` 固定，已加入忽略规则。使用 Python 自带的 `sqlite3`，不需要安装数据库服务。每次操作使用独立连接，退出上下文后提交或回滚，并关闭连接。

## 数据库初始化

首次使用时自动创建缺失的数据库文件与表；没有已有数据时，待办列表与会话菜单为空。之后重启继续读取已保存的待办、会话、摘要和工具历史。两个数据库路径都相对于应用目录固定，且被 Git 忽略。

## 删除待办事项

```text
输入：删除2026年11月4日整理房间的待办。
Human approval required
Tool: delete_todo
Arguments: {"project": "整理房间", "date": "2026-11-04"}
Approve this call? [y/n/exit]: y
Tool: Deleted todo: 整理房间, 2026-11-04.
助手：……
```

删除按“名称＋安排日期”定位，无需提供预计耗时。条件不明确时助手应先询问；未找到时返回“没有删除任何待办”。其他名称或日期的待办保留，最后一条删除后表为空，查询返回 `[]`。删除成功后立即生效，重启也会读到更新后的列表。

## 目录布局与提示词

```text
todo_list_assistant_agent/
├── AGENTS.md                     # 开发 Agent 的规范
├── CLAUDE.md                     # 相同规范，英文在前、中文在后
├── .env                          # 本应用的私有配置，不提交 Git
├── .env.example                  # 可共享的配置模板
├── __init__.py
├── __main__.py                   # Python 模块入口
├── main.py                       # 资源生命周期与应用组装
├── console.py                    # 会话菜单、输入输出和错误提示
├── config/
│   ├── __init__.py                # 只导出公开接口
│   ├── agent.py                   # Agent 摘要与执行参数
│   ├── model.py                   # 模型配置、默认值与校验
│   └── app.py                     # 路径、.env 读取与 AppConfig 组装
├── agent/
│   ├── __init__.py
│   ├── graph.py                  # 固定依赖、节点对象与流程连线
│   ├── state.py                  # 消息、摘要、工具历史和草案
│   ├── schemas.py                # 请求与生成草案的 schema
│   ├── errors.py                 # 明确的值／类型校验异常
│   ├── tools/                    # 按能力组织工具与共享工具列表
│   │   ├── __init__.py           # 组装 TOOLS 并统一导出工具
│   │   ├── time.py               # 本地日期与时间
│   │   ├── calculator.py         # 数值计算
│   │   ├── todos.py              # 保存、删除、查询待办
│   │   ├── history.py            # 通过 runtime 读取工具历史
│   │   └── draft.py              # 校验交给草案节点的请求
│   ├── middleware/               # 单次调用包装与错误格式化
│   │   ├── __init__.py           # 公开导出与包装函数组合
│   │   ├── approval.py           # 使用 interrupt 进行人工审批
│   │   └── tool_execution.py     # 执行观察与已知输入错误处理
│   ├── model.py                  # 创建聊天模型
│   ├── prompts.py                # 读取模板与动态组装提示词
│   ├── memory.py                 # 待办校验与 SQLite 增删改查
│   ├── checkpoints.py            # 检查点路径与会话查询
│   ├── nodes/                    # 图节点的执行逻辑
│   │   ├── __init__.py
│   │   ├── model.py              # 模型调用与条件路由
│   │   ├── tools.py              # 顺序任务和执行历史更新
│   │   ├── summarize.py          # token 估算和摘要更新
│   │   └── draft.py              # 结构化生成、校验与草案回复
│   └── prompt_templates/         # 只放 Markdown，不放 __init__.py
│       ├── system_prompt.md
│       ├── todo_list_prompt.md
│       ├── summary_prompt.md
│       └── draft_prompt.md
├── data/                         # 个人 SQLite 文件，不提交 Git
├── docs/                         # 中英文学习文档
└── tests/                        # 使用临时存储的离线测试
```

应用按下面的职责边界分层：

`tools/__init__.py` 组装 `TOOLS` 并统一导出各个工具，因此原有的
`from .tools import TOOLS` 导入仍然有效。工具名称、schema 与注册顺序不变。
`tools/draft.py` 只校验草案请求并返回约束，`nodes/draft.py` 仍负责结构化生成与业务检查。
这两个模块职责不同，图仍然保留原来的四个节点。

`agent/graph.py` 在 `build_graph(model, checkpointer=...)` 中一次性准备工具绑定模型与 `ToolNode`，创建四个小型节点对象并注册绑定方法。
固定依赖保存在实例字段中，每个执行方法只接收 `state`。

例如 `ModelNode` 在 `__init__` 接收模型，`model(state)` 使用 `self._model`。
对 `model_node.model`，Python 自动提供 self，LangGraph 提供 State。
不使用 partial 或自定义 Runtime.context 依赖对象。
`route_after_model()` 仍是返回下一节点名的普通路由函数。

直接调用示例（假设 Checkpointer 已打开）：

```python
graph = build_graph(model, checkpointer=checkpointer)
result = graph.invoke(
    {
        "messages": [HumanMessage(text)],
        "model_calls_this_turn": 0,
        "tool_calls_this_turn": 0,
    },
    config=config,
)
```

同一张编译后的图可用固定依赖服务不同 thread_id。节点实例字段不保存消息、摘要、
工具历史、计数等会话数据，这些仍属于 State。依赖不写入检查点，也不暴露给模型。
重启时重新创建模型和节点对象，再恢复已有会话数据。
审批／失败恢复分别使用 `graph.invoke(Command(resume=decisions), config=config)`、
`graph.invoke(None, config=config)`；只读检查点使用 `graph.get_state(config)`。
这些调用都不需要自定义 context 参数。

`ToolsNode.__init__` 创建 `@task execute_tool` 闭包，只捕获执行器。
不直接装饰实例方法，也不把 self／模型／执行器作为任务参数。
每个任务仍只接收 State／调用数据，并保存自己的结果。
`ToolNode` 仍为历史查询注入 `ToolRuntime[None, AgentState]`，模型可见参数仍是 `{}`。
工具内的 Runtime 注入与应用怎样绑定固定节点依赖是两个独立机制。

节点模块名、执行函数名与图中的注册名一一对应：

| 图注册名 | 模块 | 执行函数 |
|---|---|---|
| `model` | `agent/nodes/model.py` | `ModelNode.model(state)` |
| `tools` | `agent/nodes/tools.py` | `ToolsNode.tools(state)` |
| `summarize` | `agent/nodes/summarize.py` | `SummarizeNode.summarize(state)` |
| `draft` | `agent/nodes/draft.py` | `DraftNode.draft(state)` |

| 层次 | 位置 | 职责 |
|---|---|---|
| 入口与交互 | `main.py`、`console.py` | 资源生命周期、组装、会话菜单和输入输出 |
| Agent 执行 | `agent/graph.py`、`agent/nodes/`、`state.py`、`tools/`、`middleware/` 等 | 图组装、节点执行、State、工具、模型与提示词 |
| Agent 持久化 | `agent/memory.py`、`agent/checkpoints.py` | 待办 SQLite 增删改查、检查点会话查询 |
| 共享配置 | `config/` | 统一加载设置、默认值、校验和应用数据路径 |

`main.py` 负责组装；`agent/` 同时包含执行逻辑和持久化辅助模块。
持久化模块依赖配置，不依赖终端交互。`.env` 与 `data/` 留在应用根目录，
`config.DATA_DIR` 固定两个 SQLite 文件的位置，不随模块移动而改变。

修改助手行为时编辑 `agent/prompt_templates/` 中对应 `.md` 文件；`agent/prompts.py` 使用 UTF-8 读取它们，再将待办数据填入模板。模板在模块导入时读取，编辑后重新启动程序生效。简短的输入错误前缀保留为 `agent/prompts.py` 中的 `TOOL_ERROR_MESSAGE` 字符串。文件名使用小写，Python 常量名使用大写，二者没有必须一致的要求。节点模块通过 `from ..prompts import ...` 使用统一入口，`main.py` 通过 `from .agent.graph import build_graph` 导入图构建函数。

`main.py` 打开 Saver，通过 `threads = checkpoints.list_threads(checkpointer)` 获取普通列表，再交给 `console.py` 的 `select_thread(threads)`。菜单不访问数据库；`agent/checkpoints.py` 集中管理 `CHECKPOINTS_FILE` 和会话查询 SQL，`console.py` 管理 `select_thread()` 和 `chat()`。入口直接进入会话列表，不解析命令行参数。

`config/` 按三类职责拆分：`agent.py` 定义 `AgentConfig`，统一管理摘要参数、
图执行步数、每轮调用上限、工具历史条数与审批工具名单；`model.py` 定义和解析 `ModelConfig`；`app.py` 管理路径、
`AppConfig`、唯一的 `read_env()` 和 `load_config()` 组装逻辑。`.env` 只提供模型配置，
`config/agent.py` 只创建一份共享的 `AGENT_CONFIG = AgentConfig()`，
`load_config()` 将同一个对象呈现为 `settings.agent`；图和 reducer 直接读取这份配置。
State 字段全部保留在 `AgentState` 中。
`config/__init__.py` 只导出公开名称，不再提供单独的 Agent 配置加载或环境变量解析函数。

用户选择会话后，`main.py` 调用一次 `load_config()`，将 `settings.model` 传给
`create_model()`，`build_graph()` 和 State reducer 使用 `config/agent.py` 中的共享配置。`agent/model.py` 只创建客户端，
不读取 `.env`，不设置配置默认值。导入配置包不会读取文件，查看菜单和退出仍不需要 API Key。
测试或其他调用方可用 `load_config(env_file)` 显式选择配置文件，不改变应用的默认文件位置。

## 两种记忆怎样配合

`data/todo_checkpoints.sqlite` 按 `thread_id` 保存图状态，包括对话历史和执行进度。`data/todos.sqlite` 保存三字段待办事项。不同会话的聊天历史独立，但共用同一份待办事项；会话 ID 不是用户账号。

两个文件都能跨重启保留，且已被 Git 忽略。最新图状态保留近期原文、有损的历史摘要，每个会话近期工具调用记录（默认最多十条），以及可用时的最新待办草案。想开始新对话时在启动菜单选择 `0`，同一会话一次运行一个终端进程。

遇到预期的图、API 或存储错误时，程序结束本次终端会话，保留已经成功写入的检查点。重启后通过 `get_state(config).next` 判断是否有未完成步骤；普通失败使用 `invoke(None, config)`，
待审批请求则通过 `Command(resume=...)` 明确提供决定，再接受新输入。已经记录完成的步骤会复用；节点中断时若尚未保存结果，可能重新执行该节点。检查点和待办写入属于独立事务，因此不保证工具副作用严格只执行一次。后续模型失败也不会回滚已提交的待办。
人工审批暂停通过明确决定恢复，不走普通失败自动恢复；重跑未完成批次时复用已完成单次任务的结果。

计算器使用浮点数，适合预计耗时等日常计算，不作为精确金额计算工具。

## 延伸阅读

先跟随 `agent/nodes/tools.py` 中的 `tools()` 查看工具结果怎样成为 State 更新，再读
`agent/state.py` 中的 `add_tool_history()`，理解记录合并规则。`agent/nodes/summarize.py` 说明
token 阈值、完整轮次保留和 `RemoveMessage`。结构图、阅读顺序与练习见
[学习路线](docs/VERSIONS.zh-CN.md)。

## 离线验证

在项目根目录运行：

```bash
uv run pytest -q src/agent_apps/todo_list_assistant_agent/tests
```

测试使用模拟模型、临时配置文件和临时数据库，不需要真实密钥或网络。覆盖依赖一次性绑定、共享节点对象下的会话隔离、依赖不写入检查点、配置隔离、触发阈值、滚动摘要、工具配对、摘要失败恢复、跨进程恢复、待办工具中断恢复、工具记录数量限制、只读历史查询、runtime 注入、摘要后的工具记录保留、待办增删改查、中文输入和存储，工具观察、批准／拒绝、终端退出后续审、多次顺序审批，跨进程复用已完成任务、请求／schema 校验、草案业务检查、单次回复、重启恢复、明确保存、JSON mode 请求、普通查询、自然回复持久化、模型／工具上限、整批拒绝、新轮次重置、审批／失败恢复时的用量保留、异常分类、SDK HTTP 重试与存储失败后复用已完成写入。
