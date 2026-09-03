# Architecture & 决策记录（ADR）

## 系统分层

```
用户 · Agent 工作台（静态前端 + Nginx：泳道 / Artifact 画布 / Inspector）
        │ SSE（/api 反向代理）
FastAPI 异步网关（API Key 鉴权 · CORS 白名单 · 并发队列限流 · SSE 流式）
        │
LangGraph StateGraph 编排（5-Agent 状态机）
Planner → Researcher → Analyst → Critic ◄─(打回)─┐
                    ⇑                            │
                RAG 混合检索 ──► [quality 回路]  │
   approach_gate(HITL 审批) ◄ Enable 时 interrupt│
        ▼                                        │
   Writer → reflect(记忆) → END                  │
        ▼                                        │
    长期经验记忆(ExperienceMemory)                │
        ▼                                        │
   内置可观测层 obs.py（→ 可选迁移 Langfuse）
        ▼                                        │
   PostgreSQL + pgvector（任务持久化 + 向量检索，HNSW）
```

## ADR-001：编排框架选 LangGraph 而非 CrewAI / AutoGen

**背景**：三个主流多智能体框架都满足"多 Agent 协作"。

**决策**：LangGraph。
- **状态机可控性**：节点/边/条件路由显式，能精确表达 Critic 质量回路与护栏；CrewAI 偏"流程声明"，难做细粒度失败路径。
- **持久化**：自带 checkpointer（MemorySaver→PG），支撑断点续跑与 HITL `interrupt/resume`。
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
4 个工具：`web_search` / `sql_query`(只读+注入校验) / `python_sandbox`(隔离+超时) / `doc_parser`。

## ADR-005：评测进 CI

**理由**：不评测 = 无法证明更优。把四维评测作为 PR 门禁，任何改动都必须通过回归。
诚实原则：当前演示模式数字基于真实本地 RAG 检索，接入真实模型后以真实语义打分为准。

## ADR-006：存储分层——内存起步，SQL 演进（已落地）

**范围**：`_tasks`（观测）、`MemorySaver`（图状态）、`DocumentStore`（向量）、`ExperienceMemory`（经验）均为进程内；任务历史与向量检索已演进到 SQL。
**决策过程**：初期聚焦编排与评测，内存实现零依赖、CI 无 Key 可跑；随后抽象 `StorageBackend` / `VectorBackend` 接口，保持测试在 SQLite 上全量验证。
**当前状态（已完成演进）**：
- 任务持久化：`SqlStorage`（SQLAlchemy，SQLite/PostgreSQL 同一套 `research_tasks` schema），生产走 `ATHENA_PG_DSN` 指向 PostgreSQL，任务可跨进程回看；
- 向量检索：`PgVectorStore`（doc_chunks 表 + HNSW 索引 + 余弦距离 top-K），`ATHENA_VECTOR_STORE=postgres` 启用；
- 部署：docker-compose 一键拉起 db（pgvector/postgres）+ api + web。
**后续**：图状态 checkpointer 迁移 LangGraph `PostgresSaver`（断点续跑），接口已预留。