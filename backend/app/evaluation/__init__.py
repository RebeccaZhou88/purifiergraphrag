# @Author: RebeccaZhou
# @Description: EvalCase dataclass (separate module to avoid circular imports)
#              EvalCase 数据类定义（独立文件避免循环导入）。
from __future__ import annotations

from dataclasses import dataclass

@dataclass
class EvalCase:
    case_id: str
    scenario: str  # filter_compatibility / fault_diagnosis / batch_recall
    question: str
    expected_keywords: list[str]
