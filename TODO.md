# TODO

这里只记录尚未完成、且仍对项目有实际价值的任务。已完成的审计修复、文档同步和一次性过程步骤不在此重复记录。

## P1 — 生产安全与可靠性

- [ ] 将 `python_sandbox` 迁移到独立沙箱服务或一次性容器，提供非 root、禁网、只读文件系统、CPU/内存/PID 限额和超时控制；在此之前保持生产禁用。
- [ ] 为生产数据库建立版本化 migration，明确 `vector` 扩展、`research_tasks` 和 `doc_chunks` 的创建/升级顺序，并让应用账号只保留必要 DML 权限。

## P2 — 核心生产化

- [ ] 评估并实现 LangGraph `PostgresSaver`，让图 checkpoint 支持跨进程恢复和 HITL 断点续跑。
- [ ] 在 API Gateway/WAF 层增加跨实例限流、用户配额、SSE 生命周期预算、成本上限和审计告警。
- [ ] 明确仓库许可证；若继续使用 MIT，补充正式 `LICENSE` 文件并同步 README。

## P3 — 能力与维护优化

- [ ] 将 Golden Set 从当前 4 条扩展到覆盖主要场景的更大样本，并记录真实模型与演示模式的独立基线。
- [ ] 评估将 MCP 从进程内 FastMCP 拆为独立服务的收益、鉴权方式和部署成本。
