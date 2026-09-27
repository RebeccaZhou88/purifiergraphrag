# @Author: RebeccaZhou
# @Description: Generic relational DB extraction engine (collection + field-mapping layer)
#              通用关系库抽取引擎（"采集 + 字段映射"层）。
"""

生产替换路径：
    SQLite（本 demo，零安装）
      → MySQL：   pip install aiomysql/PyMySQL，把 _connect 换成 pymysql.connect(...)
      → Oracle：  oracledb.connect(...)
      → SQL Server：pyodbc.connect(...)
    SQL 方言差异（分页/时间字面量）在各 NodeQuery.sql 里适配，引擎本身不拼 SQL。

输出与 workbook.parse_workbook 完全一致的 parsed 结构：
    {label: [{字段key: 值, ...}], ..., "__edges__": [{"type","from","to"}, ...]}
可直接喂给 validator.validate_parsed / loader.load_parsed。

增量：每条节点查询可声明水位线列（updated_at），引擎记录各查询的最大水位值，
下次只拉变化行；边查询默认全量（MERGE 幂等，通常量不大）。
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from loguru import logger

@dataclass(frozen=True)
class NodeQuery:
    label: str
    sql: str
    # SQL 结果列名 → 图谱字段 key（registry 中的 key）
    column_map: dict[str, str]
    # 水位线列（SQL 结果中的列名）；配置后增量同步只拉该列 > 上次水位值的行
    watermark_col: str = ""
    # 值转换：图谱字段 key -> 转换函数（如客户码值 0/1/2 → none/active/pending）
    transforms: dict[str, Callable[[Any], Any]] = field(default_factory=dict)

@dataclass(frozen=True)
class EdgeQuery:
    """SQL 必须输出两列：from_code, to_code。关系类型来自白名单 rtype。"""

    rtype: str
    sql: str

class SqliteSource:
    """SQLite 实现。其他数据库继承并替换 _connect/_run 即可。"""

    def __init__(
        self,
        db_path: str | Path,
        node_queries: tuple[NodeQuery, ...],
        edge_queries: tuple[EdgeQuery, ...] = (),
        state_path: str | Path | None = None,
        source_name: str = "relational",
    ) -> None:
        self.db_path = str(db_path)
        self.node_queries = node_queries
        self.edge_queries = edge_queries
        self.state_path = Path(state_path) if state_path else None
        self.source_name = source_name
        self._state = self._load_state()

    # ---------- 连接（生产替换点） ----------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _run(self, conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return list(conn.execute(sql, params).fetchall())

    # ---------- 水位线状态 ----------

    def _load_state(self) -> dict[str, str]:
        if self.state_path and self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8")).get("watermarks", {})
            except (OSError, ValueError):
                pass
        return {}

    def _save_state(self) -> None:
        if not self.state_path:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps({"source": self.source_name, "watermarks": self._state},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ---------- 抽取 ----------

    def extract(self, *, full: bool = False) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
        """返回 (parsed, meta)。full=True 忽略水位线全量拉取。"""
        parsed: dict[str, list[dict[str, Any]]] = {}
        meta: dict[str, Any] = {"nodes": {}, "incremental": not full}

        with self._connect() as conn:
            for nq in self.node_queries:
                sql, params = self._apply_watermark(nq, full)
                rows = self._run(conn, sql, params)
                records = [self._map_row(nq, r) for r in rows]
                # 丢弃主键为空的行（源系统脏数据兜底）
                from ..registry import SPEC_BY_LABEL

                pk = SPEC_BY_LABEL[nq.label].pk
                records = [r for r in records if str(r.get(pk, "")).strip()]
                parsed[nq.label] = records
                meta["nodes"][nq.label] = len(records)

                # 推进水位线（取结果集水位线列最大值）
                if nq.watermark_col:
                    raw_vals = [str(row[nq.watermark_col]) for row in rows
                                if nq.watermark_col in row.keys()]
                    latest = max(raw_vals, default="")
                    if latest and latest > self._state.get(nq.label, ""):
                        self._state[nq.label] = latest

            edges: list[dict[str, str]] = []
            for eq in self.edge_queries:
                for row in self._run(conn, eq.sql):
                    edges.append({
                        "type": eq.rtype,
                        "from": str(row["from_code"]),
                        "to": str(row["to_code"]),
                    })
            parsed["__edges__"] = edges
            meta["edges"] = len(edges)

        self._save_state()
        logger.info(f"[{self.source_name}] 抽取完成: {meta}")
        return parsed, meta

    @staticmethod
    def _map_row(nq: NodeQuery, row: sqlite3.Row) -> dict[str, Any]:
        keys = set(row.keys())
        rec: dict[str, Any] = {}
        for col, field_key in nq.column_map.items():
            if col in keys:
                v = row[col]
                if field_key in nq.transforms:
                    v = nq.transforms[field_key](v)
                rec[field_key] = "" if v is None else v
        return rec

    def _apply_watermark(self, nq: NodeQuery, full: bool) -> tuple[str, tuple]:
        if full or not nq.watermark_col:
            return nq.sql, ()
        last = self._state.get(nq.label)
        if not last:
            return nq.sql, ()
        joiner = " WHERE " if " WHERE " not in nq.sql.upper() else " AND "
        return f"{nq.sql}{joiner}{nq.watermark_col} > ?", (last,)
