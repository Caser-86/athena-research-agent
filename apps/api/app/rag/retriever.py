"""检索统一接口 + 种子知识库。

提供 `Retriever`（代理 DocumentStore），作为 Researcher 的本地 RAG 来源。
演示环境无外部检索 Key 时，可用内置种子知识库演示「混合检索 + 引用溯源」。
未来 Researcher 将在此之上做多源检索（Tavily + 本地 RAG + MCP）。
"""

from __future__ import annotations

from app.config import get_settings
from app.rag.store import DocumentStore, make_vector_store

SEED_DOCS: list[tuple[str, str, dict]] = [
    (
        "国产新能源市场概览",
        "2025 年中国新能源乘用车渗透率突破 50%，自主品牌占据主要份额。比亚迪稳居销量第一，"
        "全年销量超 400 万辆，主攻大众主流市场并通过 e 平台 3.0 降本提速。蔚来聚焦高端纯电，"
        "以换电与用户服务体系构建差异化壁垒，坚持正向自研。小鹏押注智能驾驶与城市 NOA 落地，"
        "依靠技术标签吸引年轻用户，同时通过子品牌 MONA 下探价格带。三者策略分别对应规模化、"
        "高端化与服务化、智能化与性价比三条不同路径。",
        {"domain": "市场", "tags": ["新能源", "销量", "策略"]},
    ),
    (
        "比亚迪产品与成本策略",
        "比亚迪采用垂直一体化供应链，自研刀片电池与混动系统，叠加百万级销量摊薄研发成本，"
        "形成显著的成本优势。其产品覆盖面广，从 7 万元级到百万级均有布局。2025 年以来借助"
        "出口与海外建厂拓展全球化，多款车型登顶多国销量榜。规模效应是其价格战与利润维持的核心基础。",
        {"domain": "比亚迪", "tags": ["供应链", "成本", "全球化"]},
    ),
    (
        "蔚来换电与服务体系",
        "蔚来坚持高端豪华定位，主力车型均价在 30 万元以上。其核心竞争力是换电网络与 NIO House"
        "服务生态，通过重资产蔚来能源（NIO Power）建设换电站，缓解里程焦虑并提升复购黏性。"
        "乐道与萤火虫子品牌分别切入家庭与入门市场，用同一体系做人群下探，但换电重资产建设与"
        "持续亏损仍是其最大挑战。",
        {"domain": "蔚来", "tags": ["换电", "高端", "服务"]},
    ),
    (
        "小鹏智能驾驶技术策略",
        "小鹏把智能驾驶作为核心卖点，坚持端到端自研并用数据闭环迭代，高阶智驾（XNGP）在多个"
        "城市开放。为实现规模与现金流，推出 MONA 品牌主打高性价比走量。其策略是「技术品牌 + "
        "性价比下探」，以智驾差异化吸引用户，但在智驾尚未成为购车决定性因素前，单车毛利承压。",
        {"domain": "小鹏", "tags": ["智驾", "科技", "性价比"]},
    ),
    # ========== 技术领域（Agent / RAG / MCP）==========
    (
        "RAG 检索增强生成原理与架构",
        "RAG（Retrieval-Augmented Generation）检索增强生成：先根据用户问题从知识库检索相关文档片段，"
        "再把这些片段作为上文拼进提示词，让 LLM 基于检索到的真实资料生成回答，从而减少幻觉、降低模型"
        "对外部知识的依赖成本。典型流程为文档切片、向量化、向量检索与重排序。其优点是实现简单、可溯源、"
        "知识更新只需改库；缺点是检索质量决定上限，且对需要多步推理、工具调用、动态规划的任务支持较弱。"
        "代表性框架有 LangChain、LlamaIndex，多用于企业知识库问答、客服、文档检索等场景。",
        {"domain": "技术", "tags": ["RAG", "检索增强", "知识库", "向量检索"]},
    ),
    (
        "Agent 智能体机制与多智能体编排",
        "Agent 智能体是以 LLM 为大脑、能够自主规划并调用工具的自主系统。核心能力包括目标拆解、"
        "工具调用、多步推理和根据环境反馈迭代行动。相比单次问答，Agent 能执行需要多轮交互与动态决策的"
        "复杂任务。多智能体编排（如 LangGraph、AutoGen）将任务拆给多个角色协作：规划者拆解任务、"
        "研究者检索、分析师归纳、评审者把关、写手成文，并用状态机管理与质量回路控制流程。其优势是灵活、"
        "可处理复杂任务；代价是工程复杂度高、成本与延迟更大、易累积误差，需要护栏与评测来保障稳定性。",
        {"domain": "技术", "tags": ["Agent", "多智能体", "LangGraph", "编排"]},
    ),
    (
        "RAG 与 Agent 选型对比",
        "在构建企业知识库问答系统时，RAG 与 Agent 是两条主流路径。RAG 适合：问题相对固定、以检索文档"
        "为主、对可溯源与低延迟敏感的问答；优点是部署简单、回答可引用依据、成本可控。Agent 适合：需要"
        "多步推理、跨库查询、调用工具或动态生成子任务的高复杂任务；但更依赖护栏与评测，调试与维护成本"
        "更高。常见实践是二者结合：用 RAG 提供知识依据，用 Agent 负责任务规划与工具编排，形成「检索 + "
        "推理」的混合架构。选型应结合数据规模、问题复杂度、延迟预算、治理合规与团队工程能力综合判断。",
        {"domain": "技术", "tags": ["选型", "RAG", "Agent", "对比"]},
    ),
    (
        "MCP 模型上下文协议与工具服务",
        "MCP（Model Context Protocol）模型上下文协议是让 LLM 应用标准化接入外部工具与数据源的开放协议，"
        "通过统一接口把 web_search、sql_query、python_sandbox、doc_parser 等能力暴露给智能体。"
        "它将模型、工具与数据解耦：模型侧无需为每个工具写专用集成，工具侧按 MCP 规范实现即可被任何"
        "MCP 兼容客户端调用。在企业级 Agent 中，MCP 让智能体可在受控沙箱里执行查询、运行代码、解析文档，"
        "是构建可扩展工具生态与安全治理的关键基础设施。",
        {"domain": "技术", "tags": ["MCP", "协议", "工具", "Agent"]},
    ),
    (
        "企业知识库问答系统核心需求与评估",
        "构建企业知识库问答系统需重点考虑：业务目标（在答为准、降本增效）、数据特点（文档类型多样、"
        "权限隔离）、用户规模与实时性要求、安全合规（数据不出域、审计追溯）。关键技术评估指标包括检索"
        "召回率与精确率、回答准确率、引用可溯源率、时延与成本、以及可维护性。成熟的系统通常具备质量"
        "评测回路与 CI 门禁：用 Golden Set 回归测试，以任务成功率、引用准确率、工具选择准确率等维度"
        "持续把关，防止模型或知识库变更引入回归。",
        {"domain": "技术", "tags": ["知识库", "需求", "评估", "评测"]},
    ),
]


class Retriever:
    """持有一个向量后端的检索代理（内存或 PostgreSQL + pgvector）。"""

    def __init__(self, store=None) -> None:
        if store is None:
            store = self._make_store()
        self.store = store
        # 种子文档只注入空库；若 PG 库已有数据则跳过，避免重复
        if self.store.count() == 0:
            for text, title, meta in SEED_DOCS:
                self.store.add_document(text, {"title": title, **meta})

    @staticmethod
    def _make_store() -> DocumentStore:
        settings = get_settings()
        return make_vector_store(settings.pg_dsn, settings.vector_store or "memory")

    def search(self, query: str, k: int = 5) -> list[dict]:
        return [c.to_dict for c in self.store.hybrid_search(query, k)]


_retriever: Retriever | None = None


def get_retriever() -> Retriever:
    """进程级单例（种子知识库初始化一次）。"""
    global _retriever
    if _retriever is None:
        _retriever = Retriever()
    return _retriever