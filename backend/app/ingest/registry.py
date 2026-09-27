# @Author: RebeccaZhou
# @Description: Graph schema registry- single source of truth for the ETL pipeline
#              图谱 Schema 注册表 —— ETL 全链路的单一数据源。
"""

客户换数据时只需要改这个文件：
- template.py 按它生成 Excel 列头/示例/下拉
- validator.py 按它做必填/枚举/正则校验
- loader.py 按它的主键做 MERGE upsert
- entity_dict.py 按它从图里加载实体编码表

设计原则：标签/主键/关系类型必须与 app/graph/schema.py 的约束保持一致。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 字段值类型 → 校验/转换方式
TYPE_STR = "str"
TYPE_INT = "int"
TYPE_FLOAT = "float"
TYPE_DATE = "date"  # ISO 字符串 YYYY-MM-DD，原样写入（Neo4j 端为字符串/date 均可解析）

@dataclass(frozen=True)
class FieldSpec:
    key: str            # 程序字段名（同时是 Neo4j 属性名、JSON key）
    title: str          # Excel 列头中文名
    ftype: str = TYPE_STR
    required: bool = False
    enum: tuple[str, ...] = ()       # 合法枚举（空 = 不限制）
    pattern: str = ""               # 主键/编码正则（仅提示 + 校验，匹配用动态词典）
    desc: str = ""                  # 列说明（写入 Excel 批注/说明页）
    example: str = ""              # 示例值

@dataclass(frozen=True)
class NodeSpec:
    label: str
    sheet: str           # Excel sheet 名
    pk: str              # 主键字段 key（对应唯一约束）
    title: str           # 中文名
    fields: tuple[FieldSpec, ...]
    example_rows: tuple[dict, ...] = field(default_factory=tuple)

    def field(self, key: str) -> FieldSpec:
        return next(f for f in self.fields if f.key == key)

    @property
    def titles(self) -> list[str]:
        return [f.title for f in self.fields]

    def title_to_key(self) -> dict[str, str]:
        return {f.title: f.key for f in self.fields}

@dataclass(frozen=True)
class RelSpec:
    source: str
    rtype: str
    target: str
    desc: str

# ============================================================
# 8 类实体（字段与 backend/data/seed/*.json 一致）
# ============================================================

NODE_SPECS: tuple[NodeSpec, ...] = (
    NodeSpec(
        label="Model", sheet="Model型号", pk="name", title="型号",
        fields=(
            FieldSpec("name", "型号编码", required=True, pattern=r"^[A-Za-z0-9\-_/]+$",
                      desc="全局唯一，建议沿用客户 ERP 物料编码", example="PG-A100"),
            FieldSpec("series", "产品系列", required=True, desc="系列名", example="AquaPro"),
            FieldSpec("release_year", "上市年份", ftype=TYPE_INT, example="2022"),
        ),
        example_rows=(
            {"型号编码": "PG-A100", "产品系列": "AquaPro", "上市年份": 2022},
            {"型号编码": "PG-A200", "产品系列": "AquaPro", "上市年份": 2023},
        ),
    ),
    NodeSpec(
        label="Filter", sheet="Filter滤芯", pk="code", title="滤芯",
        fields=(
            FieldSpec("code", "滤芯编码", required=True, pattern=r"^[A-Za-z0-9\-_/]+$",
                      desc="全局唯一，沿用客户物料编码", example="FC-RO03"),
            FieldSpec("type", "滤芯类型", required=True,
                      desc="如 PP棉前置/活性炭/RO反渗透膜", example="RO反渗透膜"),
            FieldSpec("lifespan_months", "建议寿命月数", ftype=TYPE_INT, example="24"),
        ),
        example_rows=(
            {"滤芯编码": "FC-PP01", "滤芯类型": "PP棉前置", "建议寿命月数": 6},
            {"滤芯编码": "FC-RO03", "滤芯类型": "RO反渗透膜", "建议寿命月数": 24},
        ),
    ),
    NodeSpec(
        label="Fault", sheet="Fault故障", pk="code", title="故障",
        fields=(
            FieldSpec("code", "故障编码", required=True,
                      desc="建议直接复用客户内部故障代码表", example="FLT-001"),
            FieldSpec("symptom", "故障症状", required=True,
                      desc="用户口语化的一句话症状，规则引擎按它匹配问句", example="不出水"),
        ),
        example_rows=(
            {"故障编码": "FLT-001", "故障症状": "不出水"},
            {"故障编码": "FLT-004", "故障症状": "漏水"},
        ),
    ),
    NodeSpec(
        label="Cause", sheet="Cause原因", pk="id", title="原因",
        fields=(
            FieldSpec("id", "原因编码", required=True, example="CS-001"),
            FieldSpec("description", "原因描述", required=True, example="PP棉滤芯堵塞"),
        ),
        example_rows=({"原因编码": "CS-001", "原因描述": "PP棉滤芯堵塞"},),
    ),
    NodeSpec(
        label="Solution", sheet="Solution方案", pk="id", title="解决方案",
        fields=(
            FieldSpec("id", "方案编码", required=True, example="SL-001"),
            FieldSpec("description", "方案描述", required=True,
                      desc="动宾短语，如 更换RO膜", example="更换PP棉滤芯"),
            FieldSpec("cost", "参考费用元", ftype=TYPE_FLOAT, example="80"),
        ),
        example_rows=({"方案编码": "SL-001", "方案描述": "更换PP棉滤芯", "参考费用元": 80},),
    ),
    NodeSpec(
        label="Customer", sheet="Customer客户", pk="id", title="客户",
        fields=(
            FieldSpec("id", "客户编码", required=True, desc="脱敏后的客户ID", example="CUST-1001"),
            FieldSpec("name", "客户称呼", required=True, example="张先生"),
            FieldSpec("region", "所属区域", example="华东"),
        ),
        example_rows=({"客户编码": "CUST-1001", "客户称呼": "张先生", "所属区域": "华东"},),
    ),
    NodeSpec(
        label="Order", sheet="Order订单", pk="id", title="订单",
        fields=(
            FieldSpec("id", "订单编码", required=True, example="ORD-20001"),
            FieldSpec("date", "下单日期", ftype=TYPE_DATE, required=True, example="2024-06-01"),
            FieldSpec("status", "订单状态", required=True,
                      enum=("completed", "pending", "cancelled"), example="completed"),
        ),
        example_rows=({"订单编码": "ORD-20001", "下单日期": "2024-06-01", "订单状态": "completed"},),
    ),
    NodeSpec(
        label="Batch", sheet="Batch批次", pk="id", title="批次",
        fields=(
            FieldSpec("id", "批次编码", required=True, example="BATCH-2024C"),
            FieldSpec("production_date", "生产日期", ftype=TYPE_DATE, required=True,
                      example="2024-08-10"),
            FieldSpec("recall_status", "召回状态", required=True,
                      enum=("none", "pending", "active"),
                      desc="none=未召回 pending=评估中 active=召回中", example="active"),
        ),
        example_rows=(
            {"批次编码": "BATCH-2024C", "生产日期": "2024-08-10", "召回状态": "active"},
        ),
    ),
)

# ============================================================
# 10 类关系（与 app/graph/schema.py RELATIONSHIPS 一致）
# ============================================================

REL_SPECS: tuple[RelSpec, ...] = (
    RelSpec("Model", "USES", "Filter", "型号使用滤芯"),
    RelSpec("Model", "HAS_FAULT", "Fault", "型号存在故障"),
    RelSpec("Fault", "CAUSED_BY", "Cause", "故障由原因导致"),
    RelSpec("Cause", "SOLVED_BY", "Solution", "原因由方案解决"),
    RelSpec("Solution", "REQUIRES_FILTER", "Filter", "方案需更换滤芯"),
    RelSpec("Customer", "PLACED", "Order", "客户下单"),
    RelSpec("Order", "CONTAINS", "Model", "订单包含型号"),
    RelSpec("Order", "FROM_BATCH", "Batch", "订单来自批次"),
    RelSpec("Batch", "PRODUCES", "Model", "批次生产型号"),
    RelSpec("Batch", "AFFECTS", "Filter", "批次影响滤芯"),
)

# edges sheet 列头
EDGE_COLUMNS = ("关系类型", "源实体编码", "目标实体编码")

SPEC_BY_LABEL: dict[str, NodeSpec] = {s.label: s for s in NODE_SPECS}
REL_BY_TYPE: dict[str, RelSpec] = {r.rtype: r for r in REL_SPECS}
# 各标签的主键字段 key（loader / 动态词典用）
PK_BY_LABEL: dict[str, str] = {s.label: s.pk for s in NODE_SPECS}
