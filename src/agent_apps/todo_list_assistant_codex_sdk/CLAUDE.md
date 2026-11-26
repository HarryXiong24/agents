# Agent Instructions

## English

- Use English in code, source comments, prompts, and terminal text. Maintain matching English and Simplified Chinese READMEs and comparison guides.
- Keep this app independent of the two LangGraph implementations and keep its private configuration and data under this app.
- Put application behavior in Python business tools. Use the Codex SDK for threads, turns, and streaming. Explain the boundary between runtime behavior and guarantees enforced by code.
- Keep approval and quota checks before business side effects. Test with temporary storage and mock or local services. Report the limits of verification.
- Keep AGENTS.md and CLAUDE.md byte-for-byte identical, with English before Chinese.

## 中文

- 代码、注释、提示词和终端文案使用英文。同步维护英文与简体中文的 README 和对照指南。
- 保持本应用独立于两个 LangGraph 实现，私有配置和数据保存在本应用内。
- 在 Python 业务工具中实现应用行为。通过 Codex SDK 管理会话、轮次和事件流。说明 runtime 行为和代码强制保证的边界。
- 审批与配额先于业务副作用。测试使用临时存储、模拟或本地服务。如实说明验证范围。
- AGENTS.md 和 CLAUDE.md 逐字节一致，先英文后中文。
