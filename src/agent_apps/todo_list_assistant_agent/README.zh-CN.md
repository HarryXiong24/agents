# 待办清单助手 Agent

[English](README.md) | 简体中文

这是基于 LangGraph 的终端待办助手，包含五个本地工具、三个图节点、滚动对话摘要、
SQLite 会话检查点、待办数据库，以及通过自定义 State reducer 保留的近期工具执行记录（默认十条）。
每条待办仅使用 `project`（名称）、`minutes`（预计耗时）、`date`（安排日期）三个字段。

代码注释、提示词、工具说明与终端文案使用英文；助手默认用英文回答，用户明确要求时可以使用其他语言。
本文说明当前用法与设计；学习路线与功能演进统一记录在 [学习路线](docs/VERSIONS.zh-CN.md)。

| 工具 | 用途 |
|---|---|
| `get_current_time` | 获取电脑本地日期和时间 |
| `calculate` | 加、减、乘、除运算 |
| `save_todo` | 新增待办，或更新同名同日期待办的预计耗时 |
| `delete_todo` | 按名称和安排日期删除指定待办 |
| `get_tool_history` | 读取当前会话保留的近期工具执行 |

## 待办字段与存储

待办跨重启保存，由本应用的会话共享。每个会话分别保存自己的消息、摘要和工具执行记录。

| 存储字段 | 待办含义 |
|---|---|
| `project` | 待办名称 |
| `minutes` | 预计耗时，1～1440 的整数分钟 |
| `date` | 安排日期，格式为 `YYYY-MM-DD` |

保存仍需要三个字段。当前没有完成状态，表达“做完了”不会自动删除，也不能标记完成。同名同日期更新只改变耗时；修改名称或日期会新增记录，不会替换旧记录。

待办使用 `data/todos.sqlite` 数据库、`todos` 表和 `TodoItem` 类型。`agent/memory.py` 中的存储函数为 `load_todos()`、`save_todo()`、`delete_todo()`；`agent/tools.py` 中提供给模型的工具为 `save_todo` 和 `delete_todo`。会话与摘要使用 `data/todo_checkpoints.sqlite`。

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

1. 读 `agent/tools.py`：普通函数怎样通过 `@tool` 变成工具；参数和说明怎样帮助模型选择工具。
2. 读 `config/` 和 `agent/model.py`：前者负责配置读取、解析和校验，后者负责模型创建。
3. 读 `agent/memory.py` 和 `agent/prompts.py`：待办事项怎样写入数据库、查询，再进入系统提示词。
4. 读 `agent/state.py` 和 `agent/graph.py`：`call_tools()` 怎样返回新增记录，reducer 怎样合并；再看 `agent/summarization.py` 中的摘要节点。
5. 读 `agent/checkpoints.py` 和 `console.py`：存储层怎样返回会话名称列表，菜单怎样选择，以及 `chat()` 怎样将新消息和对应的 `thread_id` 交给图。
6. 最后看 `main()` 和 `__main__.py`：启动过程以及 `SqliteSaver` 的连接生命周期。

核心流程只有一条循环：

```text
用户输入 → 摘要检查 → 模型节点
             ├─ 提出工具调用 → 工具节点 → 回到模型节点
             └─ 给出回答 → 本轮结束 → 等待下一次输入
```

`bind_tools()` 让模型知道工具的名称、参数和用途；模型返回的是调用请求，真正执行工具的是 `ToolNode`。工具结果以消息形式返回给模型，用于继续判断。

模型通常可以根据对话选择工具，但不保证每次都遵循提示词。观察程序实际打印的工具提示，可以确认是否执行了工具；程序不会展示模型的内部推理。

## 对话历史持久化

运行 `uv run todo-list-assistant-agent`，选择 `0`，命名为 `home-todos`，告诉助手“我想整理日常事务”，然后退出。再次启动，按列表中显示的编号选择 `home-todos`，询问“我刚才想整理什么？”。图会根据该会话的 `thread_id` 从 `data/todo_checkpoints.sqlite` 恢复消息。

新建 `work-todos` 会使用另一段独立的历史。每次启动都由菜单选择，不需要记住或传入 ID。编号只是本次菜单的位置，会话名称才是数据库中稳定的标识。

终端每轮只传入新的 `HumanMessage`。`AgentState` 在 `MessagesState` 基础上声明可选的 `summary` 和 `tool_history` 字段，Checkpointer 将它们与近期用户消息、模型回复、工具请求和工具结果一起保存。

## 滚动对话摘要

每个新用户轮次第一次调用模型之前，摘要节点估算“已有摘要＋消息历史”的 token 数。达到配置阈值后，用“旧摘要＋较早的完整对话”生成新摘要，原样保留最近 **2 个完整用户轮次＋当前轮**。一轮包含工具请求、工具结果和最终回答，并不是一条消息。

修改 `config/agent.py` 的 `AgentConfig` 后重启。Agent 参数直接写在 Python 中，
`.env` 只保存模型配置；下面四项都应使用正整数：

```python
@dataclass(frozen=True)
class AgentConfig:
    summary_trigger_tokens: int = 500
    summary_keep_turns: int = 2
    recursion_limit: int = 20
    tool_history_limit: int = 10
```

降低摘要触发阈值可将 `summary_trigger_tokens` 改成 `300`，减少触发频率可改为 `6000`。
`summary_keep_turns` 控制保留原文的完整轮数；`recursion_limit` 限制每次图调用的执行步数，
包含摘要、模型和工具节点，不等于工具调用次数限制；`tool_history_limit` 控制每个会话
保留的工具执行记录条数。这些参数由开发者维护，不在构造配置对象时进行运行时校验。

阈值只统计摘要和对话消息，不含固定系统指令、待办事项和工具定义。使用 LangChain 基于字符的 token 估算，不是 Groq 模型精确的 tokenizer。500 适合在约 4～5 轮较详细的交流后观察，但很短的问答可能需要更多轮。即使降低阈值，也必须有超出最近两轮之外的旧对话才能压缩。

快速体验时，新建会话，依次讨论家务、工作事项、可用时间和安排偏好，请助手适当展开回答。成功压缩并完成本轮时会显示：

```text
Context: Earlier conversation summarized; recent turns kept.
```

摘要复用未绑定工具的模型，Markdown 规则要求保留目标、约束、纠正、结论和待解决问题，目标长度约 **100～150 tokens**。这是软目标。有效摘要如果没有缩短旧上下文，就跳过本次压缩，保留原消息和旧摘要并继续回答。空摘要、被截断或要求调用工具仍按错误处理，保留原状态供恢复。尝试生成摘要会增加模型请求、费用和等待时间，即使最终跳过压缩也会产生这次调用；摘要不会作为普通助手回复加入历史。

回答模型接收系统指令、数据库中的最新待办、历史摘要和近期原始消息。摘要属于历史资料，不是新指令；当前待办以数据库为准。摘要过程不会保存或删除待办事项。

压缩通过 `RemoveMessage` 更新当前图状态，SQLite 中的旧检查点暂不清理，所以数据库文件不会自动变小。重启同一会话会恢复摘要和近期消息。单条超长输入、保留轮次过长或已有历史特别大时，仍可能超过模型容量；当前不实现分块摘要或严格的上下文总量限制。

## State 维护与工具执行记录

`ToolCallRecord` 描述单条执行记录；可选的 `tool_history` 字段使用自定义
`add_tool_history(old, new)` reducer。`messages` 按消息 ID 合并，`summary` 在更新时覆盖，
`tool_history` 将新旧记录拼接后保留最近十条。节点只返回本次更新，LangGraph 按字段规则合并。

`call_tools()` 工具节点还返回本次新增的 `tool_history` 记录，包含工具名称、请求参数、
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

图为三个节点、五个工具。工具历史使用已有检查点数据库，没有独立的表；
保留条数由 `AgentConfig.tool_history_limit` 配置，默认十条；
`call_tools()` 包装 `ToolNode` 来生成记录。图的 `recursion_limit` 默认是 `20`，
没有独立的工具调用次数预算，也未使用中间件记录。

调小 `tool_history_limit` 后，新上限在下一次工具节点更新合并时生效。
恢复检查点本身不会执行 reducer，因此此前保存的记录可能暂时超过新上限，
第一次查询工具历史时也可能返回这份旧列表。

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
│   ├── graph.py                  # 摘要、模型、工具节点
│   ├── state.py                  # 消息、摘要和工具历史 reducer
│   ├── tools.py                  # 时间、计算、待办和历史查询
│   ├── model.py                  # 创建聊天模型
│   ├── prompts.py                # 读取模板与动态组装提示词
│   ├── summarization.py          # token 估算和摘要更新
│   ├── memory.py                 # 待办校验与 SQLite 增删改查
│   ├── checkpoints.py            # 检查点路径与会话查询
│   └── prompt_templates/         # 只放 Markdown，不放 __init__.py
│       ├── system_prompt.md
│       ├── todo_list_prompt.md
│       └── summary_prompt.md
├── data/                         # 个人 SQLite 文件，不提交 Git
├── docs/                         # 中英文学习文档
└── tests/                        # 使用临时存储的离线测试
```

应用按下面的职责边界分层：

| 层次 | 位置 | 职责 |
|---|---|---|
| 入口与交互 | `main.py`、`console.py` | 资源生命周期、组装、会话菜单和输入输出 |
| Agent 执行 | `agent/graph.py`、`state.py`、`tools.py` 等 | 图、State、工具、模型、提示词和摘要 |
| Agent 持久化 | `agent/memory.py`、`agent/checkpoints.py` | 待办 SQLite 增删改查、检查点会话查询 |
| 共享配置 | `config/` | 统一加载设置、默认值、校验和应用数据路径 |

`main.py` 负责组装；`agent/` 同时包含执行逻辑和持久化辅助模块。
持久化模块依赖配置，不依赖终端交互。`.env` 与 `data/` 留在应用根目录，
`config.DATA_DIR` 固定两个 SQLite 文件的位置，不随模块移动而改变。

修改助手行为时编辑 `agent/prompt_templates/` 中对应 `.md` 文件；`agent/prompts.py` 使用 UTF-8 读取它们，再将待办数据填入模板。模板在模块导入时读取，编辑后重新启动程序生效。简短的工具错误提示保留为 `agent/prompts.py` 中的 `TOOL_ERROR_MESSAGE` 字符串。文件名使用小写，Python 常量名使用大写，二者没有必须一致的要求。`agent/graph.py` 通过 `from .prompts import ...` 使用统一入口，`main.py` 通过 `from .agent.graph import build_graph` 导入图构建函数。

`main.py` 打开 Saver，通过 `threads = checkpoints.list_threads(checkpointer)` 获取普通列表，再交给 `console.py` 的 `select_thread(threads)`。菜单不访问数据库；`agent/checkpoints.py` 集中管理 `CHECKPOINTS_FILE` 和会话查询 SQL，`console.py` 管理 `select_thread()` 和 `chat()`。入口直接进入会话列表，不解析命令行参数。

`config/` 按三类职责拆分：`agent.py` 定义 `AgentConfig`，统一管理摘要参数、
图执行步数与工具历史条数；`model.py` 定义和解析 `ModelConfig`；`app.py` 管理路径、
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

两个文件都能跨重启保留，且已被 Git 忽略。最新图状态保留近期原文、有损的历史摘要，以及每个会话近期工具执行记录（默认最多十条）。想开始新对话时在启动菜单选择 `0`，同一会话一次运行一个终端进程。

遇到预期的图、API 或存储错误时，程序结束本次终端会话，保留已经成功写入的检查点。重启后通过 `get_state(config).next` 判断是否有未完成步骤，先用 `invoke(None, config)` 继续，再接受新输入。已经记录完成的步骤会复用；节点中断时若尚未保存结果，可能重新执行该节点。检查点和待办写入属于独立事务，因此不保证工具副作用严格只执行一次。后续模型失败也不会回滚已提交的待办。

计算器使用浮点数，适合预计耗时等日常计算，不作为精确金额计算工具。

## 延伸阅读

先跟随 `agent/graph.py` 中的 `call_tools()` 查看工具结果怎样成为 State 更新，再读
`agent/state.py` 中的 `add_tool_history()`，理解记录合并规则。`agent/summarization.py` 说明
token 阈值、完整轮次保留和 `RemoveMessage`。结构图、阅读顺序与练习见
[学习路线](docs/VERSIONS.zh-CN.md)。

## 离线验证

在项目根目录运行：

```bash
uv run pytest -q src/agent_apps/todo_list_assistant_agent/tests
```

测试使用模拟模型、临时配置文件和临时数据库，不需要真实密钥或网络。覆盖配置隔离、触发阈值、滚动摘要、工具配对、摘要失败恢复、跨进程恢复、待办工具中断恢复、工具记录数量限制、只读历史查询、runtime 注入、摘要后的工具记录保留、待办增删改查，以及中文输入和存储。
