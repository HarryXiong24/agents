# Agent Instructions

## English

These rules apply to this application and its descendants. Follow current user
instructions and preserve unrelated changes, especially the sibling manual agent.

- Use English for code, comments, docstrings, prompts and terminal text. Reply to
  the user in their requested language. Keep README.md/README.zh-CN.md and
  docs/COMPARISON.md/docs/COMPARISON.zh-CN.md consistent.
- README describes current usage/design. Put comparison lessons and diagrams in
  docs/. Do not automatically create numbered learning versions. Source comments
  describe current behavior, not version history.
- Use create_agent in agent/agent.py. Compose behavior through focused
  middleware in agent/middleware/ and tools in agent/tools/. Keep one complete
  middleware responsibility per module, export classes from __init__.py, and keep
  composition order in agent.py. Keep console
  interaction in console.py and resource startup in main.py. Group tools by
  capability in agent/tools/; tools/__init__.py defines and exports create_tools
  to assemble the tool list. Keep the draft tool, generator and validation in tools/draft.py.
  Do not reintroduce a
  hand-maintained StateGraph or nodes directory without a user requirement.
- Fixed models/settings belong to constructors/closures; conversation data belongs
  to AgentState. ToolRuntime is graph-injected. Keep the one-tool-per-response
  guard, budget-before-approval order and matching request/result messages.
- Only config/app.py reads this application's .env. Model settings live in
  config/model.py; Agent settings and the shared AGENT_CONFIG in config/agent.py.
  The graph and history reducer use that shared configuration. Keep the custom
  State fields together in agent/state.py. Data paths stay application-local.
- Do not copy real credentials or personal databases from another application.
  Do not migrate sibling data unless the user requests it. Keep .env and data/
  ignored. Drafts are not saved records; only explicit writes change todos.
- Distinguish prompt guidance from enforced rules, checkpoint State from model
  context, and offline tests from live-provider verification. Explain real behavior
  differences from the manual application. Do not claim exactly-once execution.
- Format only known input errors as tool results. Preserve framework interrupts;
  propagate storage/programming faults. Do not add tool/application retry loops.
  Document SDK retry settings and built-in summary context-overflow fallback.
- Update both documentation languages with behavior changes. Run relevant offline
  tests with temporary databases/fake models or mock HTTP; run Ruff and Pyright.
  Check links, diagrams, startup command, ignored paths and sibling isolation.
- Keep AGENTS.md and CLAUDE.md byte-for-byte identical. Both must contain English
  first and matching Simplified Chinese second. Update all copies together.

## 中文

这些规则适用于本应用及其子目录。遵循用户当前指令，保留无关改动，尤其是旁边的手动编排应用。

- 代码、注释、docstring、提示词和终端文案用英文；对话使用用户要求的语言。
  README.md/README.zh-CN.md 与 docs/COMPARISON.md/docs/COMPARISON.zh-CN.md 保持一致。
- README 介绍当前使用与设计，对照教学与结构图放 docs/。不自动新增数字学习版本；
  代码注释描述当前行为，不写版本历史。
- 在 agent/agent.py 使用 create_agent，通过 agent/middleware/ 的职责明确的
  中间件与 agent/tools/ 的工具组合行为。每个模块承载完整的中间件职责，
  __init__.py 统一导出类，agent.py 集中管理组合顺序。
  终端交互在 console.py，资源启动在 main.py。工具在 agent/tools/ 按能力分组；
  tools/__init__.py 定义并导出 create_tools，统一组装工具。草案工具入口、生成器与业务校验
  集中在 tools/draft.py。
  没有用户需求时不重新引入手动 StateGraph 或 nodes 目录。
- 固定模型/配置放构造函数或闭包，会话数据放 AgentState。ToolRuntime 由图注入。
  保留每次响应单工具检查、配额先于审批的顺序，以及匹配的请求/结果消息。
- 只有 config/app.py 读取本应用 .env；模型配置在 config/model.py，Agent 配置与
  共享 AGENT_CONFIG 在 config/agent.py。图与历史 reducer 使用这份共享配置。
  自定义状态字段集中在 agent/state.py，数据路径归属本应用。
- 不复制其他应用的真实凭据或个人数据库。用户未要求时不迁移旁边应用的数据。
  .env 与 data/ 保持忽略。草案不是已保存记录，只有明确写操作改变待办。
- 区分 prompt 引导与代码强制、检查点 State 与模型上下文、离线测试与真实供应商验证。
  说明与手动应用的真实差异，不声称 exactly-once 执行。
- 只把明确的输入错误格式化为工具结果；保留框架中断，向上抛出存储/程序故障。
  不叠加工具或应用重试循环；说明 SDK 重试与内置摘要的上下文溢出兜底。
- 行为变化同步更新双语文档。使用临时数据库、假模型或 mock HTTP 运行相关离线测试，
  并运行 Ruff、Pyright。检查链接、结构图、启动命令、忽略路径与原应用隔离。
- AGENTS.md 与 CLAUDE.md 保持逐字节相同，先英文后对应简体中文，变更时同步更新。
