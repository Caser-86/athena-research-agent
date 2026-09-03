# Athena 项目面试讲解稿

## 一、开场（30 秒）

"面试官您好，我今天带来的是一个**多智能体研究平台 Athena**。它不是简单的 Chatbot，而是一个让多个 Agent 协作完成复杂研究任务的系统——比如输入'对比三家新能源车企 2024 年报'，系统会自动拆解问题、检索资料、交叉分析、质量评审，最终输出一份带引用来源的研究报告。"

---

## 二、技术架构（1 分钟）

"整体架构分四层：

1. **前端**：现代 Agent 工作台，三栏布局——左侧 Agent 泳道（每个 Agent 独立轨道、状态实时高亮），中间 Artifact 画布（计划 → 检索 → 分析 → 评审 → 报告按阶段切换），右侧 Inspector（可观测 KPI + 时延瀑布 + 工具调用链 + Trace）。
2. **网关**：FastAPI + SSE 流式推送，支持 API Key 鉴权和 CORS 收敛，带并发任务队列（信号量限流）。
3. **编排引擎**：基于 LangGraph 的 StateGraph，五个节点协作——Planner 拆任务、Researcher 检索、Analyst 综合分析、Critic 质量评审、Writer 出报告。Critic 不通过会打回 Researcher 补充，最多重试 N 轮。
4. **基础设施**：PostgreSQL + pgvector 做向量和任务持久化；自研 MCP 工具服务暴露 web_search、sql_query 等工具；LLM 接的是火山方舟 deepseek-v4-flash；全部 Docker Compose 一键编排，CI 跑单测 + 评测门禁。"

---

## 三、核心难点与解决方案（2 分钟）

### 难点 1：多智能体协作的质量控制
"Critic 节点会按证据充分性、引用对齐、逻辑一致性三个维度打分。如果分数低于阈值，会带着反馈把状态回传给 Researcher，定向补充检索和分析。我在路由层加了 max_iterations 护栏，防止无限循环。"

### 难点 2：检索效果与成本的平衡
"Researcher 并行检索多个子任务，每个子任务最多取 3 条结果并截断 snippet，压缩上下文长度。RAG 层实现了向量 + BM25 + RRF 重排序，向量后端可以在内存和 PostgreSQL/pgvector 之间切换。"

### 难点 3：工具调用与可观测性
"我没有让节点直接调外部 API，而是抽象了一层 MCP 工具包装，统一调用链并写入可观测 span。这样前端能展示每个 Agent 的 token、成本、时延，以及 MCP 工具调用链。"

### 难点 4：工程化部署
"项目用 Docker Compose 一键拉起 db + api + web。我在 Nginx 里用 Docker 内置 DNS 动态解析 api 服务，解决了容器启动顺序导致的 host not found 问题。"

---

## 四、现场演示（2 分钟）

1. 打开 http://localhost:8888
2. 展示顶部状态栏：模型状态（deepseek-v4-flash）+ 队列状态 + 累计成本
3. 输入问题："对比比亚迪、蔚来、理想 2024 年报的核心财务指标与差异化战略"，Enter 发送
4. 观察左侧 Agent 泳道依次高亮：Planner → Researcher → Analyst → Critic → Writer
5. 中间 Artifact 画布按阶段切换：执行计划清单 → 检索结果卡片 → 综合分析 → Critic 评审 → 最终 Markdown 报告
6. 右侧 Inspector 实时刷新：LLM 调用数、Token、成本（约 ¥0.04/轮）、Agent 时延瀑布、MCP 工具链
7. 点击顶部"历史"按钮唤出历史任务抽屉，展示真实任务已落库 PostgreSQL，可点击回看

---

## 五、数据说话（30 秒）

"真实模型跑一个单轮研究任务：

- 5 次 LLM 调用，约 9500 token
- 总成本约 ¥0.043
- 总时延约 40 秒
- Writer 和 Researcher 是耗时大头

这套系统让我能清楚知道每个 Agent 花了多少时间、多少钱，而不是一个黑盒。"

---

## 六、收尾（30 秒）

"项目已开源在 GitHub，带 CI 门禁——每次提交自动跑 45 项单测和四维评测，评测不达标直接阻断合并，保证改动质量。整个项目覆盖了一条完整的 Agent 产品链路：工作流设计、检索增强、工具链、可观测、评测、部署。后续还可以接入 Langfuse 做更完整的企业级 trace，或者接入真实搜索 API 替代演示检索。"

---

## 七、可能的问题与回答

**Q：为什么用 LangGraph 而不是自己写状态机？**
"LangGraph 提供了内置的 checkpoint、interrupt、stream 机制，支持 Human-in-the-Loop 和断点续跑。自己写状态机容易在并发、持久化、重入上踩坑。"

**Q：Critic 打回重试会不会很贵？**
"会，所以演示容器我把 max_iterations 收敛到 1，日常 CI 保持 3。实际生产可以按任务复杂度动态调整，或者让 Critic 只检查关键点。"

**Q：MCP 工具服务是独立的吗？**
"当前是进程内 FastMCP，便于演示；生产可以拆成独立进程，通过 stdio/sse 与主服务通信， LangGraph 侧调用接口不变。"
