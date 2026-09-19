# Architecture & 决策记录（ADR）

## 系统分层

```
用户 · Agent 工作台（静态前端 + Nginx：同源代理 / 服务端鉴权 / 基础限流）
        │ SSE（/api 反向代理）
FastAPI 异步网关（API Key 鉴权 · CORS 白名单 · 并发队列限流 · SSE 流式）
        │
LangGraph StateGraph 编排（5-Agent 状态机）
Planner → Researcher → Analyst → Critic ◄─(打回)─┐
                    ⇑                            │
                RAG 混合检索 ──► [quality 回路]  │
    approval_gate(HITL 审批) ◄ Enable 时 interrupt│
        ▼                                        │
   Writer → reflect(记忆) → END                  │
        ▼                                        │
    长期经验记忆(ExperienceMemory)                │
        ▼                                        │
   内置可观测层 obs.py（→ 可选迁移 Langfuse）
        ▼                                        │
    PostgreSQL + pgvector（任务历史 + 向量检索，HNSW；图 checkpoint 仍为内存）
```

## 当前部署边界

- 开发 Compose 默认启动 `db`、`api`、`web`，数据库使用本地演示凭据并只绑定宿主机回环地址。
- 生产应叠加 `deploy/docker-compose.production.yml`，由环境变量/Secret 提供数据库、模型、API Key、CORS 和 Host 白名单；不要单独把根 Compose 当作公网生产配置。
- Web 由 Nginx 提供同源页面和 `/api` 反向代理；API 直接暴露时，仍需要外部网关提供统一认证、分布式限流和配额。

## ADR-001：编排框架选 LangGraph 而非 CrewAI / AutoGen

**背景**：三个主流多智能体框架都满足"多 Agent 协作"。

**决策**：LangGraph。
- **状态机可控性**：节点/边/条件路由显式，能精确表达 Critic 质量回路与护栏；CrewAI 偏"流程声明"，难做细粒度失败路径。
- **持久化**：当前使用进程内 `MemorySaver` 支撑演示和测试；`PostgresSaver`/跨进程 checkpoint 是后续生产化任务，HITL 当前可在单进程内 `interrupt/resume`。
- **成本可控**：我们关注"每次 LLM 调用是否值得"，LangGraph 的显式图让我们能插桩每一次调用。

**代价**：样板代码略多。换取的是可测试性与可观测性——这正是本项目的核心命题。

## ADR-002：Critic 质量回路 + 迭代护栏

**问题**：单 Agent 无法自我校验，多 Agent 又可能循环失控。

**决策**：
- Critic 按「证据充分性 / 引用对齐 / 逻辑一致性」三维打分。
- `< 阈值` 打回 Researcher **带反馈重新检索**（多轮 findings 累积，保留证据链）。
- 护栏：`iteration > max_iterations(3)` 强制放行 + Planner 初始轮次计数，杜绝无限循环。

**验收标准**：演示模式下可见"打回→重试→通过"的真实轨迹，且最多跑满 `max_iterations` 轮。

## ADR-003：检索用混合检索 + RRF，而非纯向量

**理由**：中文 + 垂直领域，纯向量丢专有名词（模型名、品牌、缩写）召回；BM25 兜底词面匹配。

**实现**：向量余弦 + BM25，RRF 融合，结果按融合分重排。重排可再升级 bge-reranker 做交叉重排。
**存储演进（已完成）**：进程内 DocumentStore → **PostgreSQL + pgvector（HNSW 索引）**，通过 `ATHENA_VECTOR_STORE=postgres` 切换，`VectorBackend` 协议（add_document / hybrid_search / count）统一两种后端。

## ADR-004：工具统一走 MCP，而非裸 Function Calling

**理由**：MCP 是标准化协议——工具服务可独立部署、跨客户端复用、自带 schema 描述与鉴权边界。
4 个工具：`web_search` / `sql_query`（演示级只读校验与行数限制）/
`python_sandbox`（演示级受限子进程与超时，生产必须替换为真正沙箱）/ `doc_parser`（本地读取需配置 `ATHENA_DOC_ROOT`，空值时禁用）。

## ADR-005：评测进 CI

**理由**：不评测 = 无法证明更优。把四维评测作为 PR 门禁，任何改动都必须通过回归。
诚实原则：当前演示模式数字基于真实本地 RAG 检索，接入真实模型后以真实语义打分为准。

## ADR-006：存储分层——内存起步，SQL 演进（已落地）

**范围**：`_tasks`（LLM/MCP 观测）、`MemorySaver`（图状态）、`DocumentStore`（向量）、`ExperienceMemory`（经验）仍有进程内实现；任务历史和端到端时延与向量检索已可演进到 SQL。
**决策过程**：初期聚焦编排与评测，内存实现零依赖、CI 无 Key 可跑；随后抽象 `StorageBackend` / `VectorBackend` 接口，保持测试在 SQLite 上全量验证。
**当前状态（已完成演进）**：
- 任务持久化：`SqlStorage`（SQLAlchemy，SQLite/PostgreSQL 同一套 `research_tasks` schema），生产走 `ATHENA_PG_DSN` 指向 PostgreSQL，任务可跨进程回看；
- 任务时延：`research_tasks.latency_ms` 保存端到端耗时，`/api/obs/summary` 基于历史样本计算 P50/P95/P99；未配置 SQL 时仍按演示模式使用进程内存储；
- 向量检索：`PgVectorStore`（doc_chunks 表 + HNSW 索引 + 余弦距离 top-K），`ATHENA_VECTOR_STORE=postgres` 启用；
- 生产数据库：`vector` 扩展由迁移/运维账号预先安装，应用启动不再自动执行 `CREATE EXTENSION`；
- 部署：docker-compose 一键拉起 db（pgvector/postgres）+ api + web。
**未完成**：图状态 checkpointer 迁移 LangGraph `PostgresSaver`（跨进程断点续跑）；接口已预留，但当前不能把 `MemorySaver` 描述为生产级持久化。
