# Agent Instructions

## English

These rules apply to `todo_list_assistant_agent` and its descendants. Follow the user's
current instructions when they change an existing convention. Inspect the current
implementation before describing behavior; preserve unrelated user changes.

### 1. Language

- Use English for code, source comments, docstrings, tool descriptions, prompts,
  and terminal messages. Use the user's requested language in conversation.
- Keep English as the default documentation entry point. Maintain matching
  English and Simplified Chinese editions:
  - [README.md](README.md) and [README.zh-CN.md](README.zh-CN.md).
  - [docs/VERSIONS.md](docs/VERSIONS.md) and
    [docs/VERSIONS.zh-CN.md](docs/VERSIONS.zh-CN.md).
- Keep both editions consistent in capabilities, constraints, paths, examples,
  and verification results.

### 2. README: current usage and design

- Describe how the application works now: setup, configuration, commands, tools,
  data fields, persistence, module responsibilities, and current limitations.
- Do not include learning-version numbers, upgrade narratives, historical
  implementations, or planned features presented as available functionality.
- Link to the learning guide for evolution details. Keep README usage-oriented;
  put detailed lessons in the learning guide and local implementation explanations
  in source comments.

### 3. Learning guides: version history

- Start both learning guides with an overview table containing the version,
  additions or changes, and learning focus.
- For every learning version, document goals, scope, changed components, a
  component diagram, reading order, exercises, and verification.
- Follow version boundaries confirmed by the user. Do not create a new learning
  version automatically for every fix, rename, or small extension.
- Keep each version's additions in its own section. Clearly identify historical
  code and names instead of presenting them as current interfaces.

### 4. Source comments

- Explain current behavior, design reasons, execution order, non-obvious syntax,
  and framework conventions. Match detail to the user's learning needs.
- Do not put learning-version labels or change-history notes in source comments
  or docstrings. Describe what the code does rather than when it was introduced.
- Explain important boundaries where relevant: node updates versus full State,
  reducer merge rules, runtime injection, checkpoint persistence, and what the
  model actually receives.
- Avoid comments that merely repeat obvious assignments. Update or remove stale
  comments whenever the implementation changes.

### 5. Function and tool docstrings

- Describe purpose and, when useful, input requirements, return values, side
  effects, and error behavior.
- Tool docstrings also guide the model: explain when to use the tool, required
  arguments, validation constraints, operation scope, and result meaning.
- Distinguish developer comments from model-visible descriptions: ordinary `#`
  comments are not sent to the model; `@tool` uses the function docstring as its
  default tool description.
- Explain injected parameters for developers, including who provides them and
  when. Do not imply that the model supplies hidden runtime or State values.

### 6. Prompts and capability claims

- Use tool descriptions for individual tool contracts and the system prompt for
  shared role, selection, sequencing, and response rules. Keep them consistent
  with actual tool names, schemas, return values, and behavior.
- Document only implemented capabilities. Distinguish model guidance from a
  programmatically enforced guarantee.
- Distinguish saved State from model-visible context, recent retained records
  from complete history, and mock-model tests from real-model verification.
- Label illustrative traces and pseudocode as examples. Do not present expected
  model wording or untested behavior as observed results.

### 7. Component diagrams

- Provide a diagram for every documented learning version, highlighting its
  additions or changes.
- Reflect actual control flow and data flow. Clearly distinguish registered
  graph nodes from helper functions, tools, reducers, State fields, and storage.
- Do not count every diagram box as a graph node. Keep diagram labels, prose,
  and implementation consistent.

### 8. Synchronization and verification

- Update both documentation languages alongside changes to behavior, tool
  contracts, configuration, storage, prompts, or module responsibilities.
- Keep README focused on the resulting application and update the relevant
  learning-version section with its teaching context.
- For documentation-only edits, check local links and anchors, Markdown fences,
  diagrams, bilingual consistency, and agreement with the source. Do not add
  tests that only mirror wording.
- For behavior changes, run relevant offline tests and applicable formatting,
  lint, and type checks. Use mock models and temporary storage; do not use real
  secrets or personal databases for tests. Report what was actually checked and
  any meaningful verification gaps.

### 9. AGENTS.md and CLAUDE.md

- Keep `AGENTS.md` and `CLAUDE.md` identical in content, ordering, and formatting.
- Both files must contain the English instructions first, followed by the
  matching Simplified Chinese instructions.
- When a rule changes, update both languages in both files in the same change.
  Verify that the files remain byte-for-byte identical.

### 10. Module boundaries and configuration

- Keep composition and terminal interaction in `main.py` and `console.py`.
  Keep Agent execution and its persistence helpers in `agent/`, including
  `memory.py` and `checkpoints.py`. Put graph node implementations in `agent/nodes/`;
  keep `agent/graph.py` focused on fixed dependency assembly, registration, edges,
  and compilation. Node modules and execution methods match graph registration keys;
  classes are ModelNode, ToolsNode, SummarizeNode, and DraftNode. Bind fixed models,
  settings, and executors through constructors when building the graph. Instance fields
  hold dependencies only; conversation data stays in AgentState. Do not require a
  custom Context for fixed dependencies. Tasks capture executors in closures and
  receive only State/call data; never pass self, clients, executors, or Runtime as
  serialized task arguments. Preserve registered node/task names and execution order.
  ToolRuntime injection inside tools remains supported independently of this layout.
- Treat `config/` as the configuration entry point, with a public API in
  `config/__init__.py` and environment-file reading confined to `config/app.py`.
  Group settings into `agent.py`, `model.py`, and `app.py`; keep `__init__.py`
  limited to re-exports. Define `AgentConfig` and `ModelConfig` in their respective
  modules, and `AppConfig` plus loading/assembly functions in `app.py`. Keep model
  environment-file reads, defaults, parsing, and validation in this package. Define
  Agent settings directly in `AgentConfig`, without a separate Agent loader or
  environment variables. Create one shared `AGENT_CONFIG` in `config/agent.py`;
  expose it through `AppConfig.agent` and let the graph and State reducer read it.
  Keep all State fields in `AgentState`, without a dynamic schema factory. Startup
  loads `AppConfig` once and passes model settings to the model builder, which does not
  read `.env` or select configuration defaults.
- Resolve database paths through `config.DATA_DIR`. Keep `.env` and `data/` at the
  application root, preserving personal data locations when modules move.
- Adjust boundaries when user requirements change, synchronizing imports, tests,
  and documentation.

## 中文

这些规则适用于 `todo_list_assistant_agent` 及其子目录。用户当前指令调整已有约定时，
以用户指令为准。描述行为前先检查当前实现，保留与任务无关的用户改动。

### 1. 语言

- 代码、源码注释、docstring、工具描述、提示词与终端文案使用英文；对话使用用户要求的语言。
- 文档默认入口使用英文，维护对应的英文与简体中文文件：
  - [README.md](README.md) 与 [README.zh-CN.md](README.zh-CN.md)。
  - [docs/VERSIONS.md](docs/VERSIONS.md) 与
    [docs/VERSIONS.zh-CN.md](docs/VERSIONS.zh-CN.md)。
- 两种语言的能力、约束、路径、示例和验证结果保持一致。

### 2. README：当前用法与设计

- 描述应用当前怎样工作，包括安装启动、配置、命令、工具、数据字段、持久化、模块职责和限制。
- 不包含学习版本号、升级过程、历史实现，也不把规划中的功能写成已有能力。
- 功能演进通过链接指向学习文档。README 保持使用导向，详细教学放在学习文档，
  局部实现说明放在代码注释。

### 3. 学习文档：版本演进

- 两份学习文档开头都提供总览表，列出版本、增加或调整的内容、学习重点。
- 每个学习版本记录目标、范围、变化组件、结构图、阅读顺序、练习和验证方式。
- 版本边界以用户确认为准，不因每次修复、改名或小扩展自动新建学习版本。
- 各版本的新增内容归属各自章节。历史代码和名称明确标注，不当作当前接口介绍。

### 4. 代码注释

- 解释当前行为、设计原因、执行顺序、不直观的语法和框架约定；详细程度匹配用户的学习需要。
- 源码注释和 docstring 不写学习版本标签或修改历史，说明代码做什么，而不是何时引入。
- 按需解释关键边界：节点增量更新与完整 State、reducer 合并规则、runtime 注入、
  检查点持久化，以及模型实际收到哪些内容。
- 避免重复显而易见的赋值；实现变化时同步更新或删除失效注释。

### 5. 函数与工具 docstring

- 说明用途，必要时补充输入要求、返回值、副作用和错误行为。
- 工具 docstring 还要指导模型选择工具，写清调用时机、必需参数、校验约束、操作范围和结果含义。
- 区分开发者注释与模型可见描述：普通 `#` 注释不会发给模型，
  `@tool` 默认使用函数 docstring 作为工具描述。
- 为开发者解释注入参数由谁提供、何时传入，不暗示模型负责提供隐藏的 runtime 或 State。

### 6. 提示词与能力描述

- 工具描述负责单个工具的使用契约，System Prompt 负责整体角色、选择、执行顺序和回答规则；
  两者与实际工具名、参数结构、返回值和行为保持一致。
- 只描述已实现能力，区分给模型的行为指引与代码强制保证。
- 区分已保存 State 与模型可见上下文、近期保留记录与完整历史、模拟模型测试与真实模型验证。
- 示意过程和伪代码明确标为示例，不把预期模型文案或未验证行为写成实际观察结果。

### 7. 组件结构图

- 每个学习版本提供结构图，突出新增或调整部分。
- 图反映实际控制流和数据流，明确区分注册的图节点、辅助函数、工具、reducer、State 字段和存储。
- 不把图中的每个方框都算作图节点，保持图示、文字与实现一致。

### 8. 同步与验证

- 行为、工具契约、配置、存储、提示词或模块职责变化时，同步更新两种语言的文档。
- README 描述调整后的应用，相关学习版本章节记录教学背景。
- 仅修改文档时，检查本地链接与锚点、Markdown 代码围栏、结构图、双语一致性和源码一致性；
  不新增仅验证文字相同的测试。
- 行为变化时运行相关离线测试，以及适用的格式、lint 和类型检查。
  测试使用模拟模型与临时存储，不使用真实密钥或个人数据库。
  如实报告实际检查内容和有意义的验证缺口。

### 9. AGENTS.md 与 CLAUDE.md

- `AGENTS.md` 与 `CLAUDE.md` 的内容、顺序和格式保持完全一致。
- 两份文件都先写英文规范，再写对应的简体中文规范。
- 规则变化时，在同一次修改中同步更新两份文件的两种语言，并检查文件逐字节一致。

### 10. 模块边界与配置

- `main.py` 与 `console.py` 负责组装和终端交互；Agent 执行及其持久化辅助模块放在
  `agent/`，包括 `memory.py` 和 `checkpoints.py`。图节点实现集中放在 `agent/nodes/`，
  `agent/graph.py` 专注固定依赖组装、节点注册、连边与编译。
  节点模块名、执行方法名与图注册名一致，类名为 ModelNode、ToolsNode、SummarizeNode、DraftNode。
  构图时通过构造函数绑定固定模型、配置和执行器；实例字段只保存依赖，会话数据保留在 AgentState。
  固定依赖不要求自定义 Context。任务通过闭包捕获执行器，参数只接收 State／调用数据，
  不将 self、客户端、执行器或 Runtime 作为序列化任务参数。保持注册节点／任务名与执行顺序。
  工具内的 ToolRuntime 注入独立于这种布局，继续保留。
- `config/` 是配置统一入口，由 `config/__init__.py` 提供公开 API，
  环境文件读取集中在 `config/app.py`，按 `agent.py`、`model.py`、`app.py` 三类组织；
  `__init__.py` 只重新导出接口，各自模块定义 `AgentConfig` 和 `ModelConfig`，
  `app.py` 定义 `AppConfig` 及读取、组装函数，统一管理模型配置的读取、默认值、解析和校验。
  Agent 参数直接在 `AgentConfig` 中定义，不添加独立 Agent 加载函数或环境变量。
  在 `config/agent.py` 中创建一份共享的 `AGENT_CONFIG`，通过 `AppConfig.agent` 呈现，
  图和 State reducer 直接读取这份配置。State 字段全部保留在 `AgentState` 中，不使用动态 schema 工厂。
  启动时一次加载 `AppConfig`，再向模型工厂传入模型配置；模型工厂不读取 `.env`，
  不自行选择配置默认值。
- 通过 `config.DATA_DIR` 定位数据库，`.env` 与 `data/` 保留在应用根目录，模块移动时保持个人数据位置。
- 用户需求调整边界时，同步修改导入、测试和文档。
