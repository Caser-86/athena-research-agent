"""分层记忆：任务级经验记忆（长期）。

短期会话记忆由 LangGraph checkpointer（MemorySaver）负责持久化；
本模块实现**跨任务的长期经验记忆**：每次研究完成后沉淀经验，后续研究可检索复用。

- `remember(...)`: 研究结束时写入经验（策略/坑/结果）
- `recall(query, k)`: 基于关键词相似度检索历史经验，供 Planner 参考
第 4 周将把 recall 升级为向量检索（复用 RAG embedder）。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Experience:
    task_id: str
    question: str
    reflection: str
    pitfalls: list[str]
    outcome: str
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "question": self.question,
            "reflection": self.reflection,
            "pitfalls": self.pitfalls,
            "outcome": self.outcome,
        }


def _keywords(text: str) -> set[str]:
    return set(
        w.lower()
        for w in re.findall(r"[a-zA-Z0-9_+-]+", text)
    ) | set(re.findall(r"[\u4e00-\u9fff]", text))


class ExperienceMemory:
    def __init__(self, max_items: int = 200) -> None:
        self._items: list[Experience] = []
        self._max = max_items

    def remember(
        self,
        task_id: str,
        question: str,
        reflection: str,
        pitfalls: list[str],
        outcome: str,
    ) -> None:
        self._items.append(
            Experience(
                task_id=task_id, question=question, reflection=reflection,
                pitfalls=pitfalls, outcome=outcome,
            )
        )
        if len(self._items) > self._max:
            self._items = self._items[-self._max:]

    def recall(self, query: str, k: int = 3) -> list[Experience]:
        """按关键词重叠召回历史经验（基于重看与重试经验，帮助后续研究少走弯路）。"""
        q = _keywords(query)
        scored = []
        for exp in self._items:
            body = _keywords(exp.question + " " + exp.reflection + " ".join(exp.pitfalls))
            overlap = len(q & body)
            if overlap > 0:
                scored.append((overlap, exp))
        scored.sort(key=lambda x: -x[0])
        return [exp for _, exp in scored[:k]]

    def count(self) -> int:
        return len(self._items)


_memory: ExperienceMemory | None = None


def get_memory() -> ExperienceMemory:
    global _memory
    if _memory is None:
        _memory = ExperienceMemory()
    return _memory