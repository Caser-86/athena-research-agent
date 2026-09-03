"""API 数据模型。"""

from pydantic import BaseModel, Field


class ResearchRequest(BaseModel):
    """研究任务请求。"""

    question: str = Field(..., min_length=2, max_length=2000, description="研究问题")


class CritiqueView(BaseModel):
    score: float
    passed: bool
    feedback: str


class ResearchResult(BaseModel):
    """同步运行结果：报告 + 关键状态摘要（轨迹级可视化在第 2 周前端工作台提供）。"""

    task_id: str
    question: str
    report: str
    iteration: int
    critique: CritiqueView | None = None
    plan: list[dict] = []
    findings: list[dict] = []
    analysis: str = ""
    mock_mode: bool = False
