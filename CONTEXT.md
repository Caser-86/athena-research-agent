# Project Context

## 项目目标

Athena 是一个面向研究与分析场景的多智能体平台：用户提交研究问题后，系统通过规划、检索、分析、质量评审和写作，输出带来源引用、可回放、可评测的结构化报告。

## 当前状态

项目已经具备可运行的演示版和 Docker Compose 部署链路，核心路径为 `Planner → Researcher → Analyst → Critic → HITL → Writer → reflect`。当前工作重点是生产化边界、文档同步和验证体系，而不是新增业务功能。

当前已验证的基线：

- API 测试：81 项通过。
- 离线演示评测：强制 mock 模式下 `overall=0.895`，阈值 `0.5` 通过。
- Docker：`db`、`api`、`web` 可启动；Web `/health` 和 `/api/obs/summary` 可返回 200。
- CI：配置了 pytest、评测门禁、Ruff、compileall 和主/生产 Compose 配置校验。

上述数字是当前工作树的验证快照，不代表已经完成远程 CI 或真实生产部署。真实模型评测数字属于历史基线，见 [指标说明](docs/metrics.md)。

## 已完成功能

- LangGraph 五个 Agent 的状态机编排、Critic 质量回路和最大迭代护栏。
- FastAPI API 网关、API Key 鉴权、CORS/Host 白名单、SSE 流式事件和并发队列。
- RAG 混合检索：确定性演示向量、BM25、RRF，以及可选 PostgreSQL/pgvector 后端。
- MCP 工具：`web_search`、只读 `sql_query`、受限演示 `python_sandbox`、`doc_parser`。
- HITL 审批门、经验记忆、任务历史、可观测指标和评测接口。
- 原生 JavaScript Agent 工作台：任务运行、轨迹、报告、历史回看和基础可观测视图。
- Docker Compose 开发部署、生产覆盖配置和 Nginx 同源反向代理。
- 81 项后端测试、Golden Set 评测脚本和 GitHub Actions CI 门禁。

## 当前正在开发

当前没有已由代码标记的独立功能分支；工作树处于审计和文档同步阶段。后续开发顺序以 [TODO.md](TODO.md) 为准。

## 当前技术栈

- Python 3.11+、FastAPI、Uvicorn、Pydantic Settings。
- LangGraph、OpenAI 兼容 LLM 接口、MCP。
- SQLAlchemy、PostgreSQL、pgvector、SQLite 测试后端。
- 原生 JavaScript/CSS、Nginx、Docker Compose。
- pytest、pytest-asyncio、Ruff、GitHub Actions。

## 核心架构

入口是 `apps/api/app/main.py`。API 路由调用 `graph/builder.py` 构建的 LangGraph；Agent 节点在 `graph/nodes.py` 中执行规划、检索、分析、评审和写作。RAG 位于 `rag/`，工具位于 `mcp/`，任务持久化位于 `storage.py`，观测位于 `obs.py`。`apps/web/index.html` 由 Nginx 托管，`/api` 和 `/health` 通过 Nginx 反代到 API。

当前存储边界要特别注意：任务历史和向量检索可以使用 PostgreSQL/pgvector；图状态仍使用进程内 `MemorySaver`，`PostgresSaver` 尚未落地。经验记忆和部分观测聚合也仍是进程内实现。

## 关键目录

| 路径 | 用途 |
|---|---|
| `apps/api/app/` | FastAPI、LangGraph、RAG、MCP、存储、记忆和评测代码 |
| `apps/api/tests/` | 后端单元测试和配置/前端安全契约测试 |
| `apps/web/` | 单文件工作台、Nginx 配置和 Web 镜像 |
| `deploy/` | 可选观测服务和生产 Compose 覆盖配置 |
| `docs/` | PRD、架构、指标、审计报告和架构图 |
| `scripts/` | PostgreSQL/pgvector 的显式本地运维辅助脚本 |

## 关键技术决策

- 用 LangGraph 显式表达质量回路、HITL 和迭代护栏。
- 用向量检索 + BM25 + RRF，避免中文专有名词只依赖向量召回。
- MCP 工具统一经过输入校验和观测包装；演示沙箱不作为生产安全边界。
- 开发环境保留零 Key 演示模式；生产环境必须配置 API Key、CORS、Host 白名单和外部 Secret。
- 运行时依赖与开发/测试依赖分离；容器基础镜像和主 pgvector 镜像固定 digest。
- 运行时和开发依赖分别由 `requirements.lock.txt`、`requirements-dev.lock.txt` 锁定；顶层范围文件只作为升级输入。

## 已知问题

- `python_sandbox` 仍是宿主机子进程级演示实现，生产模式已禁用；重新开放前必须迁移到真正的 OS/容器隔离服务。
- Nginx 限流是单实例按 IP 的基础护栏，跨实例配额、成本上限和统一审计需要外部 API Gateway/WAF。
- `PostgresSaver`、版本化数据库 migration 和图状态跨进程恢复尚未实现。
- Golden Set 当前只有 4 条用例；任务时延已写入任务历史，并由 `/api/obs/summary` 提供 P50/P95/P99，默认内存后端重启后不会保留历史样本。
- 仓库当前没有正式 `LICENSE` 文件，README 不应把许可证写成已确定的 MIT。

## 下一步

按优先级执行 [TODO.md](TODO.md)：先完成生产级沙箱边界和数据库 migration/checkpoint 方案，再补充分布式限流/配额、依赖锁定、评测集和许可证决策。
