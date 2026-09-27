# @Author: RebeccaZhou
# @Description: Mock business database for customer Haixi Water (ERP + MES + CRM in one demo DB)
#              模拟客户"海汐净水"的业务库（ERP + MES + CRM 三套系统同库示意）。
"""

这就是客户 IT 实际会给你的东西：
- 表名/字段名是客户风格（拼音缩写、业务黑话），与图谱字段完全不同
- 码值是客户编码体系（HX-/WL-/GZ-/PC/KH/SO），不是演示数据的 PG-/FLT-
- 状态用数字/中文（recall_status_code=0/1/2、order_state='已完成'），要做转换
- 故障-原因-方案不是三张主表，而是埋在维修工单 srv_work_order 的自由文本里，
  需要在 ETL 层做"行记录 → 实体/关系"的派生

同一份文件包含三块：
1. DDL + 演示数据（build_mock_db）
2. SQL 抽取配置 + 字段映射（NODE_QUERIES / EDGE_QUERIES）
3. 工单知识派生（derive_workorder_knowledge）
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

from .relational import EdgeQuery, NodeQuery, SqliteSource

# 本文件位于 backend/app/ingest/sources/，parents[3] 才是 backend/
DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "mock"
DB_PATH = DATA_DIR / "customer_erp.db"
STATE_PATH = DATA_DIR / "sync_state.json"
SOURCE_TAG = "mockdb:customer_erp"

# ============================================================
# 1. 建库 + 演示数据
# ============================================================

_DDL = """
DROP TABLE IF EXISTS bas_product;
DROP TABLE IF EXISTS bas_material;
DROP TABLE IF EXISTS bas_bom;
DROP TABLE IF EXISTS srv_fault;
DROP TABLE IF EXISTS srv_work_order;
DROP TABLE IF EXISTS mes_batch;
DROP TABLE IF EXISTS mes_batch_product;
DROP TABLE IF EXISTS mes_batch_material;
DROP TABLE IF EXISTS crm_customer;
DROP TABLE IF EXISTS crm_sales_order;
DROP TABLE IF EXISTS crm_order_item;

-- ERP：产品主数据
CREATE TABLE bas_product (
  product_code TEXT PRIMARY KEY,   -- 产品编码
  product_name TEXT NOT NULL,      -- 产品名称
  series_name  TEXT NOT NULL,      -- 系列
  launch_year  INTEGER,            -- 上市年份
  updated_at   TEXT NOT NULL       -- 最后修改时间（增量水位线）
);
-- ERP：物料主数据（滤芯）
CREATE TABLE bas_material (
  material_code  TEXT PRIMARY KEY, -- 物料编码
  material_name  TEXT NOT NULL,    -- 物料名称
  lifespan_month INTEGER,          -- 建议寿命（月）
  updated_at     TEXT NOT NULL
);
-- ERP：BOM 物料清单（型号 → 零件，天然就是 USES 关系）
CREATE TABLE bas_bom (
  product_code  TEXT NOT NULL,
  material_code TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  PRIMARY KEY (product_code, material_code)
);
-- 售后：故障代码表
CREATE TABLE srv_fault (
  fault_code   TEXT PRIMARY KEY,   -- 故障码
  symptom_text TEXT NOT NULL,      -- 故障现象（一句话）
  updated_at   TEXT NOT NULL
);
-- 售后：维修工单（原因/方案藏在这张表的文本里）
CREATE TABLE srv_work_order (
  wo_no                 TEXT PRIMARY KEY,  -- 工单号
  product_code          TEXT NOT NULL,
  fault_code            TEXT NOT NULL,
  cause_desc            TEXT NOT NULL,     -- 故障原因（师傅填写）
  action_desc           TEXT NOT NULL,     -- 处理措施（师傅填写）
  action_cost           REAL DEFAULT 0,    -- 维修费用
  replace_material_code TEXT,              -- 更换的物料（可空）
  updated_at            TEXT NOT NULL
);
-- MES：生产批次
CREATE TABLE mes_batch (
  batch_no           TEXT PRIMARY KEY,
  production_date    TEXT NOT NULL,
  recall_status_code INTEGER NOT NULL DEFAULT 0,  -- 0未召回 1召回中 2评估中
  updated_at         TEXT NOT NULL
);
CREATE TABLE mes_batch_product (
  batch_no     TEXT NOT NULL,
  product_code TEXT NOT NULL,
  PRIMARY KEY (batch_no, product_code)
);
CREATE TABLE mes_batch_material (
  batch_no      TEXT NOT NULL,
  material_code TEXT NOT NULL,
  PRIMARY KEY (batch_no, material_code)
);
-- CRM：客户与订单
CREATE TABLE crm_customer (
  cust_code TEXT PRIMARY KEY,
  cust_name TEXT NOT NULL,
  region    TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE crm_sales_order (
  order_no    TEXT PRIMARY KEY,
  cust_code   TEXT NOT NULL,
  order_date  TEXT NOT NULL,
  order_state TEXT NOT NULL,   -- 已完成/待发货/已取消
  updated_at  TEXT NOT NULL
);
CREATE TABLE crm_order_item (
  order_no     TEXT NOT NULL,
  product_code TEXT NOT NULL,
  batch_no     TEXT,
  qty          INTEGER DEFAULT 1,
  PRIMARY KEY (order_no, product_code)
);
"""

_T0 = "2025-03-01 09:00:00"

_ROWS: dict[str, list[tuple]] = {
    "bas_product": [
        ("HX-RO-500G", "鲸吞500反渗透净水器", "澎湃系列", 2023, _T0),
        ("HX-RO-800G", "鲸吞800反渗透净水器", "澎湃系列", 2024, _T0),
        ("HX-UF-300G", "清流300超滤净水器", "轻享系列", 2024, _T0),
    ],
    "bas_material": [
        ("WL-PP-10", "10寸PP棉滤芯", 6, _T0),
        ("WL-CTO-10", "10寸压缩活性炭棒", 12, _T0),
        ("WL-RO-500", "500加仑反渗透膜", 24, _T0),
        ("WL-UF-30", "中空纤维超滤膜组件", 18, _T0),
        ("WL-T33", "T33后置活性炭", 12, _T0),
    ],
    "bas_bom": [
        ("HX-RO-500G", "WL-PP-10", _T0),
        ("HX-RO-500G", "WL-CTO-10", _T0),
        ("HX-RO-500G", "WL-RO-500", _T0),
        ("HX-RO-500G", "WL-T33", _T0),
        ("HX-RO-800G", "WL-PP-10", _T0),
        ("HX-RO-800G", "WL-CTO-10", _T0),
        ("HX-RO-800G", "WL-RO-500", _T0),
        ("HX-RO-800G", "WL-T33", _T0),
        ("HX-UF-300G", "WL-PP-10", _T0),
        ("HX-UF-300G", "WL-UF-30", _T0),
        ("HX-UF-300G", "WL-T33", _T0),
    ],
    "srv_fault": [
        ("GZ-1001", "废水一直流不停", _T0),
        ("GZ-1002", "机器频繁启停", _T0),
        ("GZ-1003", "净水TDS偏高", _T0),
        ("GZ-1004", "出水量明显变小", _T0),
    ],
    "srv_work_order": [
        ("WO20250115001", "HX-RO-800G", "GZ-1001",
         "废水比电磁阀阀芯卡滞无法关闭", "更换废水比电磁阀", 120, None, _T0),
        ("WO20250118002", "HX-RO-500G", "GZ-1001",
         "废水管弯折造成背压异常", "梳理管路并更换废水管", 40, None, _T0),
        ("WO20250203003", "HX-RO-800G", "GZ-1002",
         "低压开关接触不良", "更换低压开关", 90, None, _T0),
        ("WO20250211004", "HX-RO-500G", "GZ-1003",
         "RO膜寿命到期脱盐率下降", "更换500加仑反渗透膜", 580, "WL-RO-500", _T0),
        ("WO20250220005", "HX-UF-300G", "GZ-1004",
         "PP棉滤芯堵塞进水不足", "更换PP棉滤芯", 80, "WL-PP-10", _T0),
    ],
    "mes_batch": [
        ("PC20250215", "2025-02-15", 0, _T0),
        ("PC20250301", "2025-03-01", 1, _T0),
        ("PC20250410", "2025-04-10", 2, _T0),
    ],
    "mes_batch_product": [
        ("PC20250215", "HX-RO-500G"),
        ("PC20250301", "HX-RO-800G"),
        ("PC20250410", "HX-UF-300G"),
    ],
    "mes_batch_material": [
        ("PC20250301", "WL-RO-500"),
    ],
    "crm_customer": [
        ("KH-88001", "林女士", "华东", _T0),
        ("KH-88002", "何先生", "华南", _T0),
        ("KH-88003", "罗女士", "西南", _T0),
    ],
    "crm_sales_order": [
        ("SO20250218003", "KH-88003", "2025-02-18", "已完成", _T0),
        ("SO20250312001", "KH-88001", "2025-03-12", "已完成", _T0),
        ("SO20250313002", "KH-88002", "2025-03-13", "已完成", _T0),
        ("SO20250415004", "KH-88001", "2025-04-15", "待发货", _T0),
    ],
    "crm_order_item": [
        ("SO20250218003", "HX-RO-500G", "PC20250215", 1),
        ("SO20250312001", "HX-RO-800G", "PC20250301", 1),
        ("SO20250313002", "HX-RO-800G", "PC20250301", 1),
        ("SO20250415004", "HX-UF-300G", "PC20250410", 1),
    ],
}

def build_mock_db(db_path: str | Path = DB_PATH) -> Path:
    """重建 SQLite 演示库（幂等：先 DROP 再建）。"""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_DDL)
        for table, rows in _ROWS.items():
            placeholders = ",".join("?" * len(rows[0]))
            conn.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)
        conn.commit()
    finally:
        conn.close()
    return path

# ============================================================
# 2. 抽取配置：客户字段 → 图谱字段（映射层是现场实施的核心工作）
# ============================================================

def _recall_code(v: Any) -> str:
    return {0: "none", 1: "active", 2: "pending"}.get(int(v), "none")

def _order_state(v: Any) -> str:
    return {"已完成": "completed", "待发货": "pending", "已取消": "cancelled"}.get(
        str(v).strip(), "pending"
    )

NODE_QUERIES = (
    NodeQuery(
        label="Model",
        sql="SELECT product_code, product_name, series_name, launch_year, updated_at "
            "FROM bas_product",
        column_map={"product_code": "name", "series_name": "series",
                    "launch_year": "release_year"},
        watermark_col="updated_at",
    ),
    NodeQuery(
        label="Filter",
        sql="SELECT material_code, material_name, lifespan_month, updated_at FROM bas_material",
        column_map={"material_code": "code", "material_name": "type",
                    "lifespan_month": "lifespan_months"},
        watermark_col="updated_at",
    ),
    NodeQuery(
        label="Fault",
        sql="SELECT fault_code, symptom_text, updated_at FROM srv_fault",
        column_map={"fault_code": "code", "symptom_text": "symptom"},
        watermark_col="updated_at",
    ),
    NodeQuery(
        label="Batch",
        sql="SELECT batch_no, production_date, recall_status_code, updated_at FROM mes_batch",
        column_map={"batch_no": "id", "production_date": "production_date",
                    "recall_status_code": "recall_status"},
        transforms={"recall_status": _recall_code},
        watermark_col="updated_at",
    ),
    NodeQuery(
        label="Customer",
        sql="SELECT cust_code, cust_name, region, updated_at FROM crm_customer",
        column_map={"cust_code": "id", "cust_name": "name", "region": "region"},
        watermark_col="updated_at",
    ),
    NodeQuery(
        label="Order",
        sql="SELECT order_no, order_date, order_state, updated_at FROM crm_sales_order",
        column_map={"order_no": "id", "order_date": "date", "order_state": "status"},
        transforms={"status": _order_state},
        watermark_col="updated_at",
    ),
)

EDGE_QUERIES = (
    EdgeQuery("USES",
              "SELECT product_code AS from_code, material_code AS to_code FROM bas_bom"),
    EdgeQuery("PRODUCES",
              "SELECT batch_no AS from_code, product_code AS to_code FROM mes_batch_product"),
    EdgeQuery("AFFECTS",
              "SELECT batch_no AS from_code, material_code AS to_code FROM mes_batch_material"),
    EdgeQuery("PLACED",
              "SELECT cust_code AS from_code, order_no AS to_code FROM crm_sales_order"),
    EdgeQuery("CONTAINS",
              "SELECT order_no AS from_code, product_code AS to_code FROM crm_order_item"),
    EdgeQuery("FROM_BATCH",
              "SELECT order_no AS from_code, batch_no AS to_code FROM crm_order_item "
              "WHERE batch_no IS NOT NULL"),
)

def build_source(db_path: str | Path = DB_PATH) -> SqliteSource:
    return SqliteSource(
        db_path=db_path,
        node_queries=NODE_QUERIES,
        edge_queries=EDGE_QUERIES,
        state_path=STATE_PATH,
        source_name=SOURCE_TAG,
    )

# ============================================================
# 3. 工单知识派生：srv_work_order 行记录 → Cause/Solution 实体 + 故障链关系
# ============================================================

def _stable_code(prefix: str, text: str) -> str:
    """用描述文本的 hash 生成稳定编码（同一原因跨工单复用时编码一致）。"""
    h = hashlib.md5(text.strip().encode("utf-8")).hexdigest()[:8].upper()
    return f"{prefix}-{h}"

def derive_workorder_knowledge(db_path: str | Path = DB_PATH) -> dict[str, list[dict[str, Any]]]:
    """扫描维修工单，去重派生出 Cause/Solution 节点和故障知识链边。

    生产里这一步通常用 LLM 做（师傅文本脏、同义表述多，见 ingest/extractor.py）；
    这里字段已经结构化，用规则演示即可。
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT DISTINCT product_code, fault_code, cause_desc, action_desc, "
            "action_cost, replace_material_code FROM srv_work_order"
        ).fetchall()
    finally:
        conn.close()

    causes: dict[str, dict[str, Any]] = {}
    solutions: dict[str, dict[str, Any]] = {}
    has_fault: set[tuple[str, str]] = set()
    caused_by: set[tuple[str, str]] = set()
    solved_by: set[tuple[str, str]] = set()
    requires: set[tuple[str, str]] = set()

    for r in rows:
        cause_id = _stable_code("CS", r["cause_desc"])
        sol_id = _stable_code("SL", r["action_desc"])
        causes[cause_id] = {"id": cause_id, "description": r["cause_desc"]}
        sol = {"id": sol_id, "description": r["action_desc"], "cost": float(r["action_cost"] or 0)}
        solutions[sol_id] = sol

        has_fault.add((r["product_code"], r["fault_code"]))
        caused_by.add((r["fault_code"], cause_id))
        solved_by.add((cause_id, sol_id))
        if r["replace_material_code"]:
            requires.add((sol_id, r["replace_material_code"]))

    def edges(pairs: set[tuple[str, str]], rtype: str) -> list[dict[str, str]]:
        return [{"type": rtype, "from": a, "to": b} for a, b in sorted(pairs)]

    return {
        "Cause": list(causes.values()),
        "Solution": list(solutions.values()),
        "__edges__": edges(has_fault, "HAS_FAULT")
        + edges(caused_by, "CAUSED_BY")
        + edges(solved_by, "SOLVED_BY")
        + edges(requires, "REQUIRES_FILTER"),
    }

def extract_customer_graph(
    db_path: str | Path = DB_PATH, *, full: bool = False
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """总入口：结构化表抽取 + 工单知识派生，合并为一个 parsed 批次。"""
    parsed, meta = build_source(db_path).extract(full=full)
    derived = derive_workorder_knowledge(db_path)

    for label in ("Cause", "Solution"):
        parsed[label] = derived[label]
        meta["nodes"][label] = len(derived[label])
    parsed["__edges__"] = parsed.get("__edges__", []) + derived["__edges__"]
    meta["edges"] = len(parsed["__edges__"])
    return parsed, meta
