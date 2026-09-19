# Athena · 企业级多智能体研究与分析平台

[![CI](https://github.com/Caser-86/athena-research-agent/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Caser-86/athena-research-agent/actions)
![Python](https://img.shields.io/badge/python-3.11+-blue)

输入一个研究问题，5 个专业智能体（Planner / Researcher / Analyst / Critic / Writer）基于 LangGraph 状态机协作，产出**带引用的结构化研究报告**，全程轨迹事件可流式推送、可回放、可评测。

> 当前已实现并通过本地验证：编排闭环 + RAG 混合检索 + MCP 工具 + HITL + 分层记忆 + 四维评测（CI 门禁）+ 可选 PostgreSQL/pgvector 持久化 + API 鉴权与 CORS/Host 收敛 + 并发任务队列 + 历史回看 + Agent 工作台前端（Docker Compose 部署）。生产级沙箱、图状态 checkpoint 和分布式配额仍未完成。
> 项目状态：[CONTEXT](CONTEXT.md) / [TODO](TODO.md)；技术文档：[PRD](docs/PRD.md) / [metrics](docs/metrics.md) / [architecture](docs/architecture.md) / [安全审计](docs/security-audit.md) / [架构图](docs/architecture.svg) / [面试讲解稿](docs/interview-script.md)

## 架构总览

![architecture](docs/architecture.svg)

```
用户问题
  │
  ▼
Planner ──► Researcher ──► Analyst ──► Critic ──┬─(通过/达迭代上限)──► 审批门(HITL) ──► Writer ──► reflect ──► 报告
  ▲           │                                 │
  └───────────┴─────(不通过：带反馈重新检索)─────┘
```

- **Planner**：将问题拆解为子任务清单（结构化 JSON 输出）

- **Researcher**：按子任务并行检索（Tavily 联网 / 本地 RAG 混合检索），提取带 `[S#]` 来源标注的事实

- **Analyst**：交叉验证、矛盾检测，形成综合分析

- **Critic**：按证据充分性/引用对齐/逻辑一致性打分；低于阈值则**打回 Researcher 重做**（迭代护栏：最多 N 轮）

- **审批门（HITL）**：高风险动作触发人工审批（可配置，默认自动放行）

- **Writer**：产出带 `[S1]` 行内引用的 Markdown 报告，结论可溯源

- **reflect**：研究结束后沉淀经验到长期记忆，供后续研究复用

## 技术栈

| 层  | 技术                                                                       |
| -- | ------------------------------------------------------------------------ |
| 编排 | LangGraph（StateGraph + 质量回路 + MemorySaver / HITL interrupt）              |
| 服务 | FastAPI（异步 + SSE 流式）                                                     |
| 模型 | OpenAI 兼容接口（DeepSeek / GLM / 通义等），无 Key 走演示模式                            |
| 检索 | RAG 混合检索（向量 + BM25 + RRF）+ Tavily；向量检索可选 PostgreSQL + **pgvector**（HNSW） |
| 工具 | MCP 工具服务（web\_search / sql\_query / python\_sandbox / doc\_parser）       |
| 记忆 | 长期经验记忆（ExperienceMemory）                                                 |
| 评测 | Golden Set + 四维指标 + LLM-as-judge 校准（Kappa），可进 CI                         |
| 测试 | pytest + pytest-asyncio（无 Key 全链路可跑）                                     |

## 快速启动

### 方式一：Docker Compose 一键部署（推荐）

```powershell
# 根目录 .env 配置模型与网关安全项（可复制 .env.example）
docker compose up -d --build

# 前端工作台：http://localhost:8888
# 健康检查：  http://localhost:8888/health
```

编排内容：`db`（PostgreSQL + pgvector）+ `api`（FastAPI）+ `web`（Nginx 静态托管 + 反向代理）。
Docker 部署时，生产模式、CORS/Host 白名单、API Key 和显式映射的模型配置以根目录 `.env` 为准；
`apps/api/.env` 作为未在 Compose 显式映射的 Embedding/Tavily 等补充配置来源。
配置 `ATHENA_API_KEY` 时，Compose 会把同一个 Key 仅注入 Web 容器内的 Nginx
反向代理；前端不从 URL 读取 Key，也不会把 Key 暴露给浏览器。

生产环境请叠加 `deploy/docker-compose.production.yml`，它会要求数据库凭据、PostgreSQL DSN、
模型凭据、API Key、CORS 来源和 Host 白名单，不会沿用根 Compose 的开发数据库密码，也不会把数据库端口
映射到宿主机：

```powershell
docker compose -f docker-compose.yml -f deploy/docker-compose.production.yml up -d --build
```

生产变量可参考根目录 `.env.example`。`ATHENA_PG_DSN` 中的密码必须按 URI 规则编码；已有 PostgreSQL
数据卷不会因修改 Compose 环境变量而自动更改用户密码，请先按运维流程迁移凭据并备份。

### 方式二：本地开发

```powershell
cd apps/api
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.lock.txt

# 无 Key 演示模式（开箱即用，验证编排回路）
Copy-Item .env.example .env
python -m uvicorn app.main:app --reload --port 8000

# 接入真实模型：编辑 .env，填入 ATHENA_LLM_API_KEY / ATHENA_LLM_BASE_URL / ATHENA_LLM_MODEL
```

### 前端工作台

现代 Agent UI 三栏布局（参考 LangGraph Studio / Claude Artifacts 风格）：

- **左侧 Agent 泳道**：每个 Agent 独立轨道，运行中高亮、完成变绿、打回变红，可折叠展开

- **中间 Artifact 画布**：按执行阶段动态切换产物——执行计划清单 → 检索结果卡片 → 综合分析 → Critic 评审 → 最终报告

- **右侧 Inspector**：可观测 KPI（LLM 调用/工具/成本/Token）+ Agent 时延瀑布 + MCP 工具调用链 + 实时 Trace

## API

> **鉴权**：配置 `ATHENA_API_KEY` 后，除 `/health` 外全部业务路由需要
> `Authorization: Bearer <key>` 或 `X-API-Key: <key>` 请求头，否则返回 401；
> 未配置时保持开放（仅本地/内网演示）。生产环境必须配置 `ATHENA_API_KEY`。**CORS** 由 `ATHENA_CORS_ALLOWED_ORIGINS`
> 白名单收敛，未配置则本地全放开。生产环境设置 `ATHENA_ENVIRONMENT=production`；此时
> 必须配置 CORS 白名单和 `ATHENA_ALLOWED_HOSTS` Host 白名单，且 `/docs`、`/redoc`、`/openapi.json` 默认关闭；生产环境同时禁用演示级
> `python_sandbox` 与按任意路径读取 SQLite 的 MCP 能力。

Docker Web 网关会对 `/api/research/run` 和 `/api/research/stream` 做按来源地址的基础速率限制；
直接暴露 API 端口时仍应在外部网关配置统一限流、认证和配额。

| 方法   | 路径                              | 说明                                                                                  |
| ---- | ------------------------------- | ----------------------------------------------------------------------------------- |
| GET  | `/health`                       | 健康检查（含 mock 模式标识）                                                                   |
| POST | `/api/research/run`             | 同步运行，返回报告 + 最终状态（含轨迹摘要）                                                             |
| POST | `/api/research/stream`          | SSE 流式：逐 Agent 推送 `agent_start` / `agent_end` / `tool` / `human_decision` / `final` |
| GET  | `/api/research/tasks`           | 历史任务列表（摘要字段 + 报告预览，供前端渲染）                                                           |
| GET  | `/api/research/tasks/{task_id}` | 查询历史任务详情（回看/复跑）                                                                     |
| GET  | `/api/research/queue`           | 并发队列状态：运行中 / 排队任务 + 并发上限（`asyncio.Semaphore` 限流）                                    |
| POST | `/api/rag/search`               | RAG 混合检索结果（向量 + BM25 + RRF），供工作台演示与溯源                                               |
| GET  | `/api/eval/summary`             | 四维指标评测汇总（含 Kappa 与 CI 门禁通过情况）                                                       |
| GET  | `/api/eval/cases`               | 分用例评测明细                                                                             |
| GET  | `/api/obs/summary`              | 可观测性聚合：LLM 次数 / token / 成本 / 时延 / 任务 P50/P95/P99 / 按 Agent 分账 / 最近任务              |
| GET  | `/api/obs/spans`                | 本场会话全部 span 明细                                                                      |
| POST | `/api/obs/reset`                | 清空观测（演示前调用）                                                                         |

### 可观测性（零依赖，可平滑迁移 Langfuse）

内置轻量观测层（`app/obs.py`）采集每次 LLM 调用的 token / 成本 / 时延，并按 Agent 分账，
同时记录任务级"打回次数、总成本、端到端时延"，并在 `task_latency_ms` 中提供 P50/P95/P99。
任务端到端时延写入 `research_tasks.latency_ms`，配置 SQL 后端时可跨进程统计；默认内存后端重启后样本会清空。
成本按 `llm_price_per_1m_input/output` 单价核算；
演示模式 token 为字符估算（synthetic），真实模式读取模型 usage 真值。前端评测看板内嵌成本卡片。
如需完整 trace 平台，可自部署 `deploy/docker-compose.observability.yml`（Langfuse + pgvector），
span 契约已收敛，迁移只需转发 obs 写入。该可选编排文件不会提供默认密码、占位密钥或
浮动镜像标签；启动前可复制 `deploy/.env.example` 为 `deploy/.env`，填写文件头部列出的变量，
并使用已审核的镜像版本或 digest。

### 可插拔存储层

`app/storage.py` 抽象 `StorageBackend`，实现历史任务持久化：

- **InMemoryStorage**（默认）：进程内字典，零依赖，测试/演示用；

- **SqlStorage**：SQLAlchemy 通用关系型后端，`ATHENA_PG_DSN` 启用。SQLite 与 PostgreSQL 走同一套
  `research_tasks` schema（含 JSON 列）。调用单元测试在真实 SQLite 上全量验证（含跨连接读回），
  生产切换为 `postgresql://` DSN 即可，为后续 LangGraph `PostgresSaver`（断点续跑）留有接口。
 生产使用 `ATHENA_VECTOR_STORE=postgres` 前，请由迁移/运维账号预先安装 `vector` 扩展；生产应用启动不会以运行账号执行扩展 DDL。

```powershell
# 项目内 SQLite 持久化
$env:ATHENA_PG_DSN="sqlite:///athena.db"
# 或 PostgreSQL
$env:ATHENA_PG_DSN="postgresql://user:pass@host:5432/athena"
```

### SSE 事件示例

```
event: agent_start
data: {"agent": "planner", "iteration": 1}

event: agent_end
data: {"agent": "critic", "iteration": 1, "score": 6.0, "passed": false, "feedback": "证据不足，需补充..."}

event: human_decision
data: {"approved": true, "auto": true, "question": "..."}

event: final
data: {"report": "# 研究报告\n..."}
```

### 调用示例

```powershell
# 同步运行
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/research/run `
  -ContentType "application/json" -Body '{"question": "对比三个国产新能源品牌的销量与策略"}'

# SSE 流式
curl -N -X POST http://127.0.0.1:8000/api/research/stream `
  -H "Content-Type: application/json" -d '{"question": "对比三个国产新能源品牌的销量与策略"}'
```

## 目录结构

```
CONTEXT.md                         项目现状、架构边界和已知问题
TODO.md                            当前未完成任务（按优先级）
apps/
├── api/
│   ├── app/
│   │   ├── main.py              FastAPI 入口
│   │   ├── config.py            环境配置（pydantic-settings）
│   │   ├── llm.py               LLM 调用层（OpenAI 兼容 + JSON 结构化 + 演示模式）
│   │   ├── schemas.py           API 数据模型
│   │   ├── graph/
│   │   │   ├── state.py          ResearchState 类型定义
│   │   │   ├── nodes.py          5 个智能体节点 + 检索
│   │   │   ├── builder.py        图编排：质量回路 + 迭代护栏 + 审批门 + 记忆
│   │   │   ├── hitl.py           HITL 审批门 + 经验反思节点
│   │   │   └── events.py         事件总线（SSE 推送）
│   │   ├── obs.py                内置可观测性：token/成本/时延/按 Agent 分账/工具链
│   │   ├── storage.py            可插拔存储层：InMemoryStorage（默认）/ SqlStorage（PG/SQLite）
│   │   ├── rag/                  RAG：embedder / store(混合检索+RRF) / pg_store(pgvector) / retriever(种子库)
│   │   ├── mcp/                  MCP 工具服务（server）+ 统一调用包装（tools，含观测埋点）
│   │   ├── memory/               长期经验记忆
│   │   ├── eval/                 golden set + 四维指标 + harness
│   │   └── api/
│   │       ├── routes.py         研究路由（run / stream / tasks / queue / 并发限流）
│   │       ├── rag_routes.py     RAG 检索路由
│   │       ├── eval_routes.py    评测看板路由（summary / cases）
│   │       └── obs_routes.py     可观测性路由（summary / spans / reset）
│   ├── tests/                    全部单元测试（无 Key 可跑，81 项）
│   ├── requirements.txt
│   ├── requirements.lock.txt     运行时可复现依赖
│   ├── requirements-dev.lock.txt 开发/测试可复现依赖
│   ├── pyproject.toml
│   └── .env.example
├── web/                          Agent 工作台前端（单文件应用）
│   ├── index.html                三栏布局：Agent 泳道 / Artifact 画布 / Inspector
│   ├── nginx.conf                静态托管 + /api 反向代理（Cache-Control: no-store）
│   └── Dockerfile
docker-compose.yml                db(pgvector) + api + web 开发编排
deploy/docker-compose.production.yml 生产配置覆盖（必填凭据与白名单）
.github/workflows/ci.yml          单测 + 评测回归 + 静态检查（GitHub Actions）
docs/                             PRD / metrics / architecture / security-audit / 架构图 / 面试讲解稿
```

## 测试与评测

```powershell
# 本地开发
cd apps/api
pytest -v                          # 无需 API Key，验证完整链路

# 全量评测，未达标 exit 1
python -m app.eval.harness --threshold 0.5
```

当前本地全量 **81 项 pytest 测试通过**；GitHub Actions CI 已配置单测、评测回归、Ruff、compileall、文档契约以及主/生产 Compose 配置校验，会在 push、PR 和手动触发时执行。

历史真实模型评测基线（deepseek-v4-flash，3 轮迭代，golden set=4）：overall **0.8775 → PASS**；对照单轮 0.8025——Critic 打回回路带来覆盖率 0.67→0.92、成功率 0.25→0.75（详见 [metrics](docs/metrics.md)）。当前无 Key 演示评测与真实模型基线分开记录。
