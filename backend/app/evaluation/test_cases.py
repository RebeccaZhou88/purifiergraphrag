# @Author: RebeccaZhou
# @Description: Evaluation cases: 204 auto-generated (3 scenarios) plus 17 manual cases
#              评估用例：自动生成 204 条（3 场景）+ 原 17 条手工用例。
from __future__ import annotations

from . import EvalCase  # noqa: F401  (re-export from __init__)
from .test_cases_generated import GENERATED_CASES

# 原手工用例（保留，case_id 加前缀区分）
MANUAL_CASES: list[EvalCase] = [
    EvalCase("MAN-F-01", "filter_compatibility", "PG-A100 能用哪些滤芯？",
             ["FC-PP01", "FC-CTO02", "FC-RO03", "FC-Post04"]),
    EvalCase("MAN-F-02", "filter_compatibility", "PG-A200 支持的滤芯清单",
             ["FC-PP01", "FC-RO06", "FC-Post04"]),
    EvalCase("MAN-F-03", "filter_compatibility", "PG-B150 用的是哪种膜？",
             ["FC-UF05", "超滤膜"]),
    EvalCase("MAN-F-04", "filter_compatibility", "PG-B300 与 PG-A100 的 RO 膜是否相同？",
             ["FC-RO03"]),
    EvalCase("MAN-F-05", "filter_compatibility", "哪些型号使用了 FC-PP01 滤芯？",
             ["PG-A100", "PG-A200", "PG-B150", "PG-B300"]),
    EvalCase("MAN-D-01", "fault_diagnosis", "PG-A100 不出水可能是什么原因？",
             ["CS-001", "堵塞"]),
    EvalCase("MAN-D-02", "fault_diagnosis", "PG-A100 制水量下降的原因",
             ["RO膜", "CS-003", "破损"]),
    EvalCase("MAN-D-03", "fault_diagnosis", "PG-A200 漏水怎么排查？",
             ["CS-004", "密封缺陷", "CS-005", "接口"]),
    EvalCase("MAN-D-04", "fault_diagnosis", "故障 FLT-002 的解决要换哪个滤芯？",
             ["FC-CTO02", "FC-Post04"]),
    EvalCase("MAN-D-05", "fault_diagnosis", "PG-B150 出水有异味怎么办？",
             ["CS-002", "前置活性炭", "CS-006", "后置活性炭"]),
    EvalCase("MAN-D-06", "fault_diagnosis", "PG-B300 指示灯报警的原因与方案",
             ["CS-003", "RO膜", "更换"]),
    EvalCase("MAN-R-01", "batch_recall", "BATCH-2024C 是否在召回？",
             ["recalled", "召回"]),
    EvalCase("MAN-R-02", "batch_recall", "BATCH-2024C 召回影响哪些客户的订单？",
             ["CUST-1004", "CUST-1005", "CUST-1001", "ORD-20004", "ORD-20005", "ORD-20006"]),
    EvalCase("MAN-R-03", "batch_recall", "受 BATCH-2024C 影响的客户应如何处理？",
             ["免费更换", "SL-004", "FC-RO06"]),
    EvalCase("MAN-R-04", "batch_recall", "BATCH-2024A 是否有召回？",
             ["none", "未召回", "无召回"]),
    EvalCase("MAN-R-05", "batch_recall", "BATCH-2024C 涉及的滤芯编码是什么？",
             ["FC-RO06"]),
    EvalCase("MAN-R-06", "batch_recall", "哪些批次生产了 PG-A200？",
             ["BATCH-2024A", "BATCH-2024C"]),
]

TEST_CASES: list[EvalCase] = GENERATED_CASES + MANUAL_CASES

def get_cases(scenario: str | None = None) -> list[EvalCase]:
    if scenario:
        return [c for c in TEST_CASES if c.scenario == scenario]
    return list(TEST_CASES)
