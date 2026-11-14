# Todo List Assistant — create_agent

[English](README.md)

这是使用 **LangChain `create_agent` 与中间件** 实现的终端待办助手。
原来的[手动 LangGraph 应用](../todo_list_assistant_agent/README.zh-CN.md)保持独立。
新应用拥有自己的配置与数据库，不导入、不修改原应用的个人数据。

## 启动

在仓库根目录执行：

```bash
uv sync --locked
cp src/agent_apps/todo_list_assistant_create_agent/.env.example src/agent_apps/todo_list_assistant_create_agent/.env
```

在新应用的 `.env` 中设置 `GROQ_API_KEY`，然后启动：

```bash
uv run --locked todo-list-assistant-create-agent
```

仓库虚拟环境已经安装好时，也可以执行：

```bash
.venv/bin/python -m agent_apps.todo_list_assistant_create_agent
```

启动后进入会话列表。选择已有会话，或输入 `0` 并填写新名称。
输入 `exit` 或 `quit` 退出。查看菜单、退出不需要 API key；第一次调用 Agent
才会保存新会话。终端支持中文输入和退格；助手默认英文回答，可以要求用中文。

## 试用示例

- “保存一个待办：整理房间，30 分钟，2026-11-15。”
- “显示 2026-11-15 的待办。”
- “把 2026-11-15 整理房间的时长更新为 45 分钟。”
- “删除 2026-11-15 整理房间。”——在审批提示中输入 `y` 或 `n`。
- “帮我安排 Python 和英语，日期 2026-11-16，总共不超过 90 分钟。”
- “保存刚才草案里的 Python。”——明确请求后才保存这一条。
- “刚才调用了哪些工具？参数和结果是什么？”

以上是输入示例，不是真实模型运行记录。工具选择和回答措辞取决于配置的模型。

## 能力与数据

| 能力 | 行为 |
|---|---|
| 待办增删改查 | 只有 `project`（名称）、`minutes`（整数，1–1440）、`date`（`YYYY-MM-DD`） |
| 更新 | 相同名称与日期覆盖时长；新名称或日期新增记录 |
| 查询 | 查询全部，或精确按名称/日期过滤；模型根据工具结果回答 |
| 删除审批 | 内置 HITL 在执行 `delete_todo` 前暂停 |
| 聊天记录 | SQLite checkpointer 根据选择的 `thread_id` 保存 State |
| 摘要压缩 | 内置中间件用摘要消息替换较早消息 |
| 工具历史 | 每个会话保留最近 10 条已完成或被拒绝的请求 |
| 安排草案 | 独立 JSON mode 模型调用，Pydantic 与业务规则校验，不写数据库 |
| 边界限制 | 每轮主模型调用、获准进入流程的工具请求配额，以及图递归限制 |

本应用的不同会话共享待办；消息、候选草案、计数与工具历史按会话隔离。
它们与原应用的数据也相互独立。暂不支持完成状态、优先级、提醒、重命名、
改期、多日期草案或日历冲突检查。

草案校验任务名称、指定日期和总时长。工具通过 `return_direct` 结束工具循环，
由展示 hook 生成一次最终回答；普通聊天仍是自由文本。
请求新草案时先清空旧候选，失败候选不会保留。保存草案后不清空候选；
候选始终代表建议，数据库才代表已经保存的内容。

## 配置与持久化

只有 `config/app.py` 读取**新应用目录内的 `.env`**。
这些模型配置不读取父目录 `.env`，也不使用 shell 中的同名环境变量。

| 配置 | 位置 | 默认值 |
|---|---|---|
| `GROQ_API_KEY` | 本地 `.env` | 聊天必填 |
| `AGENT_MODEL` | 本地 `.env` | `openai/gpt-oss-20b` |
| `GROQ_BASE_URL` | 本地 `.env` | `https://api.groq.com` |
| `temperature` / `timeout` / `max_retries` | `config/model.py` | `0` / 30 秒 / SDK 重试 1 次 |
| `summary_trigger_tokens` | `config/agent.py` | 估算 500 tokens |
| `summary_keep_messages` | `config/agent.py` | 最近 6 条消息，工具配对会调整边界 |
| `max_model_calls_per_turn` | `config/agent.py` | 6 次成功返回的主模型调用 |
| `max_tool_calls_per_turn` | `config/agent.py` | 8 个获准进入流程的请求 |
| `tool_history_limit` | `config/agent.py` | 10 条记录 |
| `approval_tools` | `config/agent.py` | `("delete_todo",)` |
| `recursion_limit` | `config/agent.py` | 80 个图执行步骤 |

摘要与草案的模型调用不计入主模型配额。SDK HTTP 重试也不会增加成功返回的
主模型次数。终端输入新消息时重置本轮计数；从检查点恢复时保留原计数。
工具请求在审批前占用配额，拒绝仍消耗一次。模型一次请求多个工具时，
配额内的整批请求会被拒绝并计数，模型可以随后逐个重发；整批超额则不执行、
不审批，直接结束本轮。此前已经提交的操作保留。

`summary_keep_messages` 数的是**消息条数，不是对话轮数**。
500 tokens 为了学习测试而设置得较低，但不保证第 4/5 轮触发，也不是完整请求的硬上限。
内置摘要在每次主模型调用前检查，并保留工具请求和结果的完整配对。
摘要放在 `messages` 内，因此没有单独的 `summary` State 字段。
即使原始消息被压缩，独立候选草案与保留的工具历史仍然存在。

以下本地文件由 Git 忽略：

```text
.env
data/todos.sqlite
data/todo_checkpoints.sqlite
```

检查点在图运行中保存；`exit` 负责退出和关闭资源，不触发额外的保存动作。
重启时会重新展示待审批操作，其他未完成步骤在接受新输入前显式恢复。
应用没有自行添加重试循环；Groq SDK 重试由 `max_retries` 控制。
内置摘要中间件另外有上下文溢出兜底：可能缩减输入后再请求一次摘要。
工具异常只有明确的输入错误会转成模型可见结果；其他故障向上抛出，
意外程序错误保留 traceback。检查点不等于跨待办写入与图保存的 exactly-once 事务。

## 结构与阅读顺序

```text
main.py / console.py         资源、菜单、聊天、审批数据
config/                      app.py、model.py、agent.py
agent/agent.py               create_agent 与中间件装配
agent/middleware/            按中间件职责拆分模块
agent/state.py               自定义字段与历史 reducer
agent/tools/                 按能力组织工具，__init__.py 统一组装
agent/schemas.py             结构化草案请求与输出模型
agent/prompts.py             Markdown 提示词加载
agent/prompt_templates/      模型可见指令
agent/memory.py              待办 SQLite 增删改查
agent/checkpoints.py         会话列表与检查点路径
agent/errors.py              共享的输入校验异常类型
```

```text
agent/middleware/
├── __init__.py
├── turn_control.py
├── history.py
├── context.py
├── tool_execution.py
└── draft_presentation.py
```

每个中间件类放在独立模块中，`__init__.py` 只统一导出类，
中间件的组合顺序由 `agent.py` 管理。
`middleware/tool_execution.py` 同时包含 `handle_tool_error()` 辅助函数，
负责格式化明确的输入错误。

```text
agent/tools/
├── __init__.py
├── time.py
├── calculator.py
├── todos.py
├── history.py
└── draft.py
```

`tools/__init__.py` 定义 `create_tools(model)`，仍然通过
`from .tools import create_tools` 导入。保存、删除、查询集中在 `todos.py`；
`draft.py` 包含绑定模型的草案工具、`DraftGenerator` 和业务校验，
`schemas.py` 定义 Pydantic 请求与输出模型。
图的 runtime 注入方式以及工具名称、schema、注册顺序保持一致。

建议先读 `agent.py`，再读 `middleware/`、`tools/__init__.py`、`state.py` 和 `tools/draft.py`。
[对照学习文档](docs/COMPARISON.zh-CN.md)解释执行流程、中间件顺序和与手动图的差异。

## 离线检查

在仓库根目录执行：

```bash
.venv/bin/python -m pytest -q src/agent_apps/todo_list_assistant_create_agent/tests -W error
.venv/bin/ruff check src/agent_apps/todo_list_assistant_create_agent
.venv/bin/ruff format --check src/agent_apps/todo_list_assistant_create_agent
uv tool run --from pyright pyright --pythonpath .venv/bin/python src/agent_apps/todo_list_assistant_create_agent
```

测试使用假模型、mock HTTP 与临时 SQLite，覆盖实际工厂/中间件流程、审批重启、
配额、摘要、草案、CRUD 校验、SDK 重试、本地配置与终端编辑。
这些检查不验证真实供应商行为，也不保证真实模型的工具选择质量。
