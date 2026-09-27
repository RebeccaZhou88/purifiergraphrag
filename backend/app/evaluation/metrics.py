# @Author: RebeccaZhou
# @Description: Evaluation metrics: accuracy, latency and ranking
#              评估指标：准确率、响应时间、按最新排名。
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

@dataclass
class CaseMetric:
    case_id: str
    scenario: str
    question: str
    expected_keywords: list[str]
    answer: str
    passed: bool
    latency_ms: int
    rank: int = 0

@dataclass
class AggMetric:
    total: int = 0
    passed: int = 0
    latencies: list[int] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return (self.passed / self.total) if self.total else 0.0

    @property
    def p95_ms(self) -> int:
        if not self.latencies:
            return 0
        xs = sorted(self.latencies)
        idx = max(0, int(len(xs) * 0.95) - 1)
        return xs[idx]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "accuracy": round(self.accuracy, 4),
            "p95_ms": self.p95_ms,
            "target_accuracy": 0.85,
            "target_p95_ms": 2000,
        }

def check_passed(answer: str, expected_keywords: list[str]) -> bool:
    """命中任一关键词即算通过（宽松匹配，避免 stub/LLM 表述差异误判）。"""
    if not answer:
        return False
    a = answer.lower()
    return any(kw.lower() in a for kw in expected_keywords)

def rank_by(metrics: list[CaseMetric]) -> list[CaseMetric]:
    """按 (passed DESC, latency ASC) 排名，rank 从 1 升序。"""
    metrics_sorted = sorted(metrics, key=lambda m: (not m.passed, m.latency_ms))
    for i, m in enumerate(metrics_sorted, 1):
        m.rank = i
    return metrics_sorted
