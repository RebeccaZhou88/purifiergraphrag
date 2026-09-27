# @Author: RebeccaZhou
# @Description: Smoke tests: verify core logic without Neo4j/LLM dependencies
#              冒烟测试：不依赖 Neo4j/LLM，验证核心逻辑可用。

import asyncio
import json

import pytest

def test_settings_defaults():
    from app.core.config import Settings

    s = Settings()
    assert s.llm_provider == "qwen"
    assert len(s.available_models) == 3
    assert s.available_models[0]["id"] == "qwen"  # 默认第一项

def test_schema_view_shape():
    from app.graph.schema import schema_view

    v = schema_view()
    assert set(v["nodes"]) == {
        "Model", "Filter", "Fault", "Cause", "Solution", "Customer", "Order", "Batch"
    }
    rel_types = {r["type"] for r in v["relationships"]}
    assert {"USES", "HAS_FAULT", "CAUSED_BY", "SOLVED_BY", "REQUIRES_FILTER",
            "PLACED", "CONTAINS", "FROM_BATCH", "PRODUCES", "AFFECTS"} <= rel_types

def test_eval_cases_count():
    from app.evaluation.test_cases import get_cases

    all_cases = get_cases()
    assert len(all_cases) >= 15
    scenarios = {c.scenario for c in all_cases}
    assert scenarios == {"filter_compatibility", "fault_diagnosis", "batch_recall"}

def test_metrics_rank_ascending():
    from app.evaluation.metrics import CaseMetric, rank_by

    ms = [
        CaseMetric("a", "x", "q", ["k"], "k", True, 200),
        CaseMetric("b", "x", "q", ["k"], "miss", False, 100),
        CaseMetric("c", "x", "q", ["k"], "k", True, 100),
    ]
    ranked = rank_by(ms)
    # passed 优先，同 passed 内 latency 升序
    assert ranked[0].case_id == "c"
    assert ranked[1].case_id == "a"
    assert ranked[2].case_id == "b"
    assert [m.rank for m in ranked] == [1, 2, 3]

def test_metrics_check_passed():
    from app.evaluation.metrics import check_passed

    assert check_passed("PG-A100 使用 FC-PP01 滤芯", ["FC-PP01"]) is True
    assert check_passed("不知道", ["FC-PP01"]) is False

def test_seed_files_present():
    """种子文件可被 seed 模块定位。"""
    from app.graph.seed import SEED_DIR

    for f in ["models.json", "filters.json", "faults.json", "causes.json",
              "solutions.json", "customers.json", "orders.json", "batches.json",
              "edges.json"]:
        assert (SEED_DIR / f).exists(), f"缺少种子文件 {f}"

def test_llm_stub_mode():
    """无 key 时启用 stub，保证可联调。"""
    from app.llm.prompts import ENTITY_EXTRACTION_SYSTEM
    from app.llm.providers import LLMProvider

    p = LLMProvider("qwen")
    assert p._stub_mode is True
    text = asyncio.get_event_loop().run_until_complete(
        p.chat(ENTITY_EXTRACTION_SYSTEM, "用户问题：PG-A100 能用哪些滤芯？")
    )
    data = json.loads(text)
    assert data["intent"] == "filter_compatibility"
