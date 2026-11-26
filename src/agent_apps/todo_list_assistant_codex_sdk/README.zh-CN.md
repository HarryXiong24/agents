# 待办助手 · Codex SDK

[English](README.md)

这是使用官方 Python Codex SDK 实现的终端待办助手。它和
[手写 LangGraph](../todo_list_assistant_agent/README.zh-CN.md)、
[`create_agent`](../todo_list_assistant_create_agent/README.zh-CN.md)
是同一个助手的三种实现，各自保存会话和待办。

在仓库根目录安装并启动：

```bash
uv sync --locked --extra codex-todo
uv run --locked --extra codex-todo todo-list-assistant-codex-sdk
```

启动后进入会话列表。输入 `0` 并命名可创建会话，选择已有编号可继续会话。
输入 `exit` 或 `quit` 退出。浏览列表不调用模型。新会话在第一个轮次开始后才进入保存列表。

将本目录的 [.env.example](.env.example) 复制为 `.env`，设置 `OPENAI_API_KEY`。
也可以使用已安装的 Codex CLI，登录本应用专用的 Codex 目录：

```bash
CODEX_HOME="$PWD/src/agent_apps/todo_list_assistant_codex_sdk/data/codex_home" codex login
```

先运行一次应用创建本地目录，再执行 CLI 登录。通过本地 `OPENAI_API_KEY`
登录后，凭据可能保存在该 Codex 目录下。可选的 `CODEX_MODEL` 对新会话和
草案生效。恢复会话使用原会话保存的模型和供应商。Python 安装包自带兼容的
runtime。[官方 Python SDK 安装说明](https://github.com/openai/codex/blob/main/sdk/python/docs/getting-started.md)

| 可以这样说 | 效果 |
|---|---|
| 保存 2026-12-04 的 Python，30 分钟。 | 保存 `project`、`minutes`、`date`。 |
| 看看 2026-12-04 的待办。 | 按精确日期或名称查询已保存的记录。 |
| 把 2026-12-04 的 Python 改成 45 分钟。 | 更新同一名称和日期的记录。 |
| 删除 2026-12-04 的 Python。 | 终端预览记录并询问 `y` 或 `n`。 |
| 给 2026-12-04 的 Python 和英语安排 90 分钟以内的草案。 | 生成经过校验的未保存草案。 |
| 保存草案里的 Python。 | 读取本会话草案，保存用户明确指定的待办。 |
| 刚才运行了哪些工具？ | 查看本会话最近 10 条工具结果，包含拒绝记录。 |
| $study-plan 为 2026-12-04 安排 90 分钟 Python 学习。 | 通过 SDK 显式调用内置技能。 |

普通回复使用自然语言。草案在独立的临时 Codex 会话中生成，使用输出 Schema，
再由 Python 校验任务名称、日期和总时长。请求新草案会替换旧候选，保存待办后仍可
读取候选。内置的 `study-plan` 和 `todo-cleanup` 支持 `$技能名` 显式触发，
模型也可通过受限的工具读取经过审阅的说明和指定参考文件。

`data/codex_home/` 保存 Codex 对话和认证。
`data/todos.sqlite` 保存本应用各会话共享的待办，以及按会话区分的草案和工具历史。
待审批操作仅在当前终端轮次有效。轮次失败或程序退出后，剩余操作需要重新请求。
已经提交的业务修改会保留。Codex 轮次失败后，重新打开终端应用并选择该会话继续。

将 [mcp.example.json](mcp.example.json) 复制为同目录的 `mcp.json`，
可启用内置番茄钟服务器，例如询问“把 70 分钟拆成番茄钟”。
外部 MCP 支持 `stdio`（`command`、`args`、`env`、`cwd`）和
`streamable_http`（`url`、`headers`）。`tools` 可限制可用工具，
`timeout` 默认 30 秒，`require_approval` 默认开启。字符串中的
`${NAME}` 从本目录 `.env` 读取。命令写 `python` 时使用当前应用的解释器。
请配置你信任的服务器。

应用每轮最多接受八次业务工具请求，轮次超时在 [config.py](config.py) 中配置。
上下文压缩及内部推理循环由 Codex 管理。应用能限制业务工具并中断超时轮次，
没有精确的内部模型调用次数上限。

建议从 [main.py](main.py) 开始，随后阅读 [runtime.py](agent/runtime.py)、
[gateway.py](agent/gateway.py) 和 [storage.py](agent/storage.py)。
[对照指南](docs/COMPARISON.zh-CN.md) 展示三种实现的执行流程和数据流。

```bash
uv run --locked --extra codex-todo pytest -q src/agent_apps/todo_list_assistant_codex_sdk/tests
TODO_TEST_CODEX_RUNTIME=1 uv run --locked --extra codex-todo pytest -q src/agent_apps/todo_list_assistant_codex_sdk/tests/test_runtime.py
```

runtime 检查使用已安装的 Codex runtime、回环模拟模型和临时数据，无须生产凭据。
