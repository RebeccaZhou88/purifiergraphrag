# -*- coding: utf-8 -*-
# @Author: RebeccaZhou
# @Description: End-to-end demo: customer relational DB -> Neo4j -> Cypher -> GraphRAG
#              端到端 Demo：客户关系库→ Neo4j → Cypher → GraphRAG
"""

在 backend/ 目录运行：
    set PYTHONPATH=.
    python scripts/mockdb_demo.py            # 全流程演示（数据保留，可继续在前端提问）
    python scripts/mockdb_demo.py --clean    # 清理 demo 数据（图节点 + SQLite 库 + 水位线）

流程：
    ① 在 SQLite 造一套客户 ERP/MES/CRM 库（表名字段都是客户风格）
    ② 用关系型 SQL 回答一个业务问题（要写多表 JOIN）
    ③ ETL：SQL 抽取 + 字段映射 + 校验 + 增量 MERGE 入 Neo4j
    ④ 同一个问题改用 Cypher 多跳（沿关系走，不用知道表怎么 JOIN）
    ⑤ GraphRAG 问答：规则引擎命中客户编码，自然语言回答
    ⑥ 增量同步：客户改了产品名、新增一条故障工单，水位线只拉变化
"""
from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.graph.neo4j_client import Neo4jClient
from app.ingest.entity_dict import entity_dict
from app.ingest.loader import load_parsed
from app.ingest.sources import customer_mock as cm
from app.ingest.validator import validate_parsed

LINE = "=" * 78

def stage(title: str) -> None:
    print(f"\n{LINE}\n{title}\n{LINE}")

# ============================================================
# ① 建客户 Mock 库
# ============================================================

def stage_build_db() -> None:
    stage("① 客户业务库（SQLite 模拟 ERP/MES/CRM）→ 建库灌数")
    path = cm.build_mock_db()
    conn = sqlite3.connect(path)
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='TABLE' ORDER BY name").fetchall()]
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    conn.close()
    print(f"数据库文件: {path}")
    for t, c in counts.items():
        print(f"  {t:<20} {c} 行")

# ============================================================
# ② 关系型 SQL 的做法（多表 JOIN）
# ============================================================

SQL_BUSINESS = """
SELECT p.product_code, f.symptom_text AS symptom,
       w.cause_desc AS cause, w.action_desc AS solution, w.action_cost AS cost
FROM srv_work_order w
JOIN bas_product p ON p.product_code = w.product_code
JOIN srv_fault    f ON f.fault_code   = w.fault_code
WHERE w.product_code = 'HX-RO-800G' AND w.fault_code = 'GZ-1001';
""".strip()

def stage_sql() -> None:
    stage("② 关系库做法：回答\"HX-RO-800G 废水一直流不停的原因和处理？\"要写 JOIN")
    print(SQL_BUSINESS)
    conn = sqlite3.connect(cm.DB_PATH)
    conn.row_factory = sqlite3.Row
    for r in conn.execute(SQL_BUSINESS):
        print(f"  → 症状: {r['symptom']}")
        print(f"    原因: {r['cause']}")
        print(f"    方案: {r['solution']}（¥{r['cost']}）")
    conn.close()
    print("  问题：换个问法/跨业务域（批次→订单→客户）就要重新拼 JOIN，且无法直接喂给 LLM 问答。")

# ============================================================
# ③ ETL 入图
# ============================================================

async def stage_etl(client: Neo4jClient, *, full: bool = True):
    stage("③ ETL：SQL 抽取 → 字段映射/码值转换 → 校验 → MERGE 增量入图")
    parsed, meta = cm.extract_customer_graph(full=full)
    print(f"抽取结果（{'全量' if full else '水位线增量'}）: {meta}")
    print("码值转换示例：mes_batch.recall_status_code 1 → recall_status 'active'；"
          "order_state '已完成' → 'completed'")

    report = validate_parsed(parsed)
    if report.warnings:
        print(f"校验 warnings（不阻断）: {report.warning_count} 条，"
              f"如增量批次引用图中已有的历史节点")
    if not report.ok:
        print("校验未通过，终止：")
        for e in report.errors:
            print(f"  [{e.sheet} 行{e.row}] {e.message}")
        raise SystemExit(1)
    print(f"校验通过：{report.stats}")

    result = await load_parsed(client, parsed, source=cm.SOURCE_TAG)
    print(f"入图完成: 新增 {result['created']}")
    print(f"          更新 {result['updated']}")
    print(f"          关系 {result['edges_merged']} 条，悬空边 {len(result['orphan_edges'])} 条")
    total = await entity_dict.load_from_graph(client)
    print(f"实体词典已刷新：{total} 个编码（rules.py 立即认识客户编码）")
    return result

# ============================================================
# ④ Cypher 多跳
# ============================================================

CYPHER_FAULT = """
MATCH (m:Model {name:'HX-RO-800G'})-[:HAS_FAULT]->(f:Fault {code:'GZ-1001'})
-[:CAUSED_BY]->(c:Cause)-[:SOLVED_BY]->(s:Solution)
OPTIONAL MATCH (s)-[:REQUIRES_FILTER]->(rf:Filter)
RETURN f.symptom AS symptom, c.description AS cause,
       s.description AS solution, s.cost AS cost, rf.code AS filter_code
""".strip()

CYPHER_RECALL = """
MATCH (b:Batch {id:'PC20250301'})
OPTIONAL MATCH (b)<-[:FROM_BATCH]-(o:Order)<-[:PLACED]-(c:Customer)
OPTIONAL MATCH (b)-[:AFFECTS]->(f:Filter)<-[:REQUIRES_FILTER]-(s:Solution)
RETURN b.recall_status AS status,
       COLLECT(DISTINCT c.id) AS customers, COLLECT(DISTINCT o.id) AS orders,
       f.code AS filter_code, s.description AS solution
""".strip()

async def stage_cypher(client: Neo4jClient) -> None:
    stage("④ 图做法：同样的问题，Cypher 沿关系走多跳，无需关心底层表怎么 JOIN")
    print("[故障链] Model → Fault → Cause → Solution → Filter")
    print(CYPHER_FAULT)
    for r in await client.run(CYPHER_FAULT):
        print(f"  → {r['symptom']}｜原因: {r['cause']}｜方案: {r['solution']}"
              f"（¥{r['cost']}）｜需换滤芯: {r['filter_code'] or '无'}")
    print("\n[召回影响链] Batch → Order → Customer；Batch → Filter → Solution")
    print(CYPHER_RECALL)
    for r in await client.run(CYPHER_RECALL):
        print(f"  → 召回状态: {r['status']}")
        print(f"    影响客户: {r['customers']}")
        print(f"    影响订单: {r['orders']}")
        print(f"    缺陷滤芯: {r['filter_code']}｜处理方案: {r['solution']}")

# ============================================================
# ⑤ GraphRAG 问答（走真实流水线：规则引擎 + LLM 流式生成）
# ============================================================

async def stage_graphrag(questions: list[tuple[str, str]]) -> None:
    stage("⑤ GraphRAG：自然语言提问 → 规则引擎(零LLM产Cypher) → 图上下文 → LLM 组织回答")
    from app.kernel.kernel import build_kernel
    from app.kernel.pipeline import GraphRAGPipeline

    pipeline = GraphRAGPipeline(build_kernel())
    for tag, q in questions:
        print(f"\n【{tag}】{q}")
        answer = ""
        async for ev in pipeline.run_stream(q):
            if ev.get("type") == "step" and ev.get("message"):
                print(f"  · {ev['step']}: {ev['message']}")
            elif ev.get("type") == "done":
                answer = ev.get("answer", "")
        print(f"  回答: {answer}")

# ============================================================
# ⑥ 增量同步：客户库发生变化
# ============================================================

def mutate_customer_db() -> None:
    """模拟第二天的业务变化：产品改名 + 新故障 + 新工单。"""
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(cm.DB_PATH)
    try:
        conn.execute(
            "UPDATE bas_product SET series_name=?, updated_at=? WHERE product_code='HX-RO-800G'",
            ("澎湃Pro系列", now),
        )
        conn.execute(
            "INSERT INTO srv_fault(fault_code, symptom_text, updated_at) VALUES (?,?,?)",
            ("GZ-1005", "净水有白色沉淀物", now),
        )
        conn.execute(
            "INSERT INTO srv_work_order VALUES (?,?,?,?,?,?,?,?)",
            ("WO20250924006", "HX-RO-500G", "GZ-1005",
             "后置活性炭老化滋生菌膜", "更换T33后置活性炭", 120, "WL-T33", now),
        )
        conn.commit()
    finally:
        conn.close()

async def stage_incremental(client: Neo4jClient) -> None:
    stage("⑥ 增量同步：客户改了系列名、新增故障 GZ-1005 和一条工单")
    mutate_customer_db()
    parsed, meta = cm.extract_customer_graph(full=False)
    changed = {k: v for k, v in meta["nodes"].items() if v}
    print(f"水位线增量只拉到变化的实体表: {changed}（其余表 0 行，不传输）")
    report = validate_parsed(parsed)
    print(f"校验: ok={report.ok}（{len(report.warnings)} 条 W8/W1 警告：增量批引用图中已有节点）")
    result = await load_parsed(client, parsed, source=cm.SOURCE_TAG)
    print(f"入图: 新增 {result['created']} / 更新 {result['updated']} / 关系 {result['edges_merged']}")
    await entity_dict.load_from_graph(client)
    await stage_graphrag([
        ("增量后的新故障", "HX-RO-500G 净水有白色沉淀物怎么办？"),
    ])

# ============================================================
# ⑦ 软删除演示：retire_missing
# ============================================================

def mutate_delete_order() -> None:
    """模拟客户从 CRM 删除了一条订单（连带订单明细）。"""
    conn = sqlite3.connect(cm.DB_PATH)
    try:
        conn.execute("DELETE FROM crm_sales_order WHERE order_no='SO20250218003'")
        conn.execute("DELETE FROM crm_order_item WHERE order_no='SO20250218003'")
        conn.commit()
    finally:
        conn.close()

async def stage_retire_missing(client: Neo4jClient) -> None:
    stage("⑦ 软删除演示：客户从 CRM 删除了订单 SO20250218003 → retire_missing=True")
    mutate_delete_order()

    # 用全量快照重扫（不用水位线，因为被删的行没有 updated_at 可被拉取）
    parsed, meta = cm.extract_customer_graph(full=True)
    print(f"全量重扫: {meta}")

    result = await load_parsed(
        client, parsed, source=cm.SOURCE_TAG, retire_missing=True
    )
    print(f"入图: 新增 {result['created']} / 更新 {result['updated']} / 退役 {result['retired']}")

    # 验证：SO20250218003 被标记为 inactive，但关系保留
    res = await client.run(
        "MATCH (o:Order {id:'SO20250218003'}) RETURN o._lifecycle AS lc"
    )
    if res:
        print(f"  Order SO20250218003 状态: {res[0]['lc']}")
    else:
        print("  Order SO20250218003 不存在（异常！）")

    res2 = await client.run(
        "MATCH (:Customer {id:'KH-88003'})-[:PLACED]->(:Order {id:'SO20250218003'}) "
        "RETURN count(*) AS c"
    )
    print(f"  KH-88003 → SO20250218003 关系仍然保留: {res2[0]['c']} 条")

    await entity_dict.load_from_graph(client)
    await stage_graphrag([
        ("软删除后问答", "KH-88003 的所有订单有哪些？"),
    ])

# ============================================================
# 清理
# ============================================================

async def clean(client: Neo4jClient) -> None:
    stage("清理 demo 数据")
    await client.write(
        "MATCH (n) WHERE n._source STARTS WITH $s DETACH DELETE n",
        {"s": cm.SOURCE_TAG},
    )
    for p in (cm.DB_PATH, cm.STATE_PATH):
        if Path(p).exists():
            Path(p).unlink()
            print(f"已删除 {p}")
    await entity_dict.load_from_graph(client)
    print(f"图谱中 demo 节点已删除，词典恢复 {entity_dict.code_count} 个编码")

def try_refresh_running_backend() -> None:
    """如果后端服务正在运行，通知它刷新词典（失败则提示手动重启）。"""
    import json as _json
    import urllib.request

    try:
        req = urllib.request.Request(
            f"http://localhost:{settings.app_port}/api/ingest/dicts/refresh", method="POST"
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = _json.loads(resp.read())
        print(f"已通知运行中的后端刷新词典: {data.get('code_count')} 个编码")
    except Exception:
        print("提示: 后端服务未运行或还是旧版本，重启后端后新数据即可被问答接口使用"
              "（或调 POST /api/ingest/dicts/refresh）")

async def amain(do_clean: bool) -> None:
    client = Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    if not await client.ping():
        raise SystemExit("Neo4j 连不上，请先 docker compose up -d neo4j")
    try:
        if do_clean:
            await clean(client)
            return
        stage_build_db()
        stage_sql()
        await stage_etl(client, full=True)
        await stage_cypher(client)
        await stage_graphrag([
            ("故障多跳", "HX-RO-800G 废水一直流不停是什么原因？该怎么处理？"),
            ("批次召回", "PC20250301 批次是不是在召回？影响哪些客户的订单？怎么处理？"),
        ])
        await stage_incremental(client)
        await stage_retire_missing(client)
        print(f"\n{LINE}\nDemo 完成。数据已保留：可打开前端问答页继续提问客户编码，"
              f"或在 Neo4j Browser 查看。\n{LINE}")
        try_refresh_running_backend()
    finally:
        await client.close()

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean", action="store_true", help="清理 demo 数据")
    args = parser.parse_args()
    asyncio.run(amain(args.clean))

if __name__ == "__main__":
    main()
