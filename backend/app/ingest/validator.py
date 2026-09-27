# @Author: RebeccaZhou
# @Description: Pre-load validator: shared rules for Excel file paths and direct DB connections
#              入图前校验器：Excel 文件路径与数据库直连路径共用同一套规则。
"""

校验规则：
  E2 必填为空          E3 类型不合法（int/float/date）
  E4 枚举值不合法      E5 编码正则不合法
  E6 同表主键重复
  E7 关系类型不合法
  E8 边端点实体类型错
  W1 sheet/实体缺失（warning，允许只交部分数据）
  W8 边端点不在本批数据中（已在图里的历史数据允许，入图时二次校验）

有 error 不允许入图；warning 不阻断。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from .registry import (
    EDGE_COLUMNS,
    NODE_SPECS,
    REL_BY_TYPE,
)
from .workbook import parse_workbook

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

@dataclass
class Issue:
    level: str        # error / warning
    code: str
    sheet: str
    row: int          # 行号（Excel 模式为表内行号；DB 模式为结果集序号）
    column: str
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level, "code": self.code, "sheet": self.sheet,
            "row": self.row, "column": self.column, "message": self.message,
        }

@dataclass
class ValidationReport:
    ok: bool
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "stats": self.stats,
            "errors": [i.as_dict() for i in self.errors],
            "warning": [i.as_dict() for i in self.warnings],
        }

def validate_workbook(data: bytes) -> tuple[ValidationReport, dict[str, list[dict[str, Any]]]]:
    """校验 xlsx 字节，返回 (报告, 解析结果)。"""
    try:
        parsed = parse_workbook(data)
    except Exception as e:
        logger.exception("工作簿解析失败")
        report = ValidationReport(ok=False)
        report.errors.append(Issue("error", "E0", "-", 0, "-", f"文件无法解析: {e}"))
        return report, {}
    return validate_parsed(parsed), parsed

def validate_parsed(parsed: dict[str, list[dict[str, Any]]]) -> ValidationReport:
    """校验"已归一化的数据批"（Excel 解析结果或数据库抽取结果共用）。"""
    report = ValidationReport(ok=True)
    stats: dict[str, int] = {}

    # --- 节点 ---
    for spec in NODE_SPECS:
        rows = parsed.get(spec.label)
        if rows is None:
            report.warnings.append(Issue(
                "warning", "W1", spec.sheet, 0, "-", "本批未包含该实体（允许部分提交）"
            ))
            continue
        stats[spec.label] = len(rows)
        seen_pk: dict[str, int] = {}
        for idx, rec in enumerate(rows, start=2):
            pk_val = str(rec.get(spec.pk, "")).strip()
            if pk_val in seen_pk:
                report.errors.append(Issue(
                    "error", "E6", spec.sheet, idx, spec.field(spec.pk).title,
                    f"主键重复: {pk_val}（首次出现在第 {seen_pk[pk_val]} 行）"
                ))
            else:
                seen_pk[pk_val] = idx

            for fspec in spec.fields:
                v = rec.get(fspec.key, "")
                title = fspec.title
                if v == "" or v is None:
                    if fspec.required:
                        report.errors.append(Issue(
                            "error", "E2", spec.sheet, idx, title, "必填项为空"
                        ))
                    continue
                # 类型
                if fspec.ftype in ("int", "float"):
                    if not _is_number(v):
                        report.errors.append(Issue(
                            "error", "E3", spec.sheet, idx, title,
                            f"类型应为数字，实际值: {v!r}"
                        ))
                elif fspec.ftype == "date" and not _DATE_RE.match(str(v)):
                    report.errors.append(Issue(
                        "error", "E3", spec.sheet, idx, title,
                        f"日期应为 YYYY-MM-DD，实际值: {v!r}"
                    ))
                # 枚举
                if fspec.enum and str(v) not in fspec.enum:
                    report.errors.append(Issue(
                        "error", "E4", spec.sheet, idx, title,
                        f"枚举值不合法: {v}（允许: {', '.join(fspec.enum)}）"
                    ))
                # 编码正则
                if fspec.pattern and not re.match(fspec.pattern, str(v)):
                    report.errors.append(Issue(
                        "error", "E5", spec.sheet, idx, title,
                        f"编码格式不匹配 {fspec.pattern}: {v}"
                    ))

    # --- 边 ---
    edges = parsed.get("__edges__", [])
    stats["edges"] = len(edges)
    pk_to_labels: dict[str, list[str]] = {}
    for spec in NODE_SPECS:
        for rec in parsed.get(spec.label, []):
            pk_to_labels.setdefault(str(rec[spec.pk]), []).append(spec.label)

    for idx, e in enumerate(edges, start=2):
        rtype, f, t = e.get("type", ""), e.get("from", ""), e.get("to", "")
        if not rtype or not f or not t:
            report.errors.append(Issue(
                "error", "E2", "edges关系", idx,
                "/".join(EDGE_COLUMNS), "关系类型/源/目标均不能为空"
            ))
            continue
        rel = REL_BY_TYPE.get(rtype)
        if rel is None:
            report.errors.append(Issue(
                "error", "E7", "edges关系", idx, EDGE_COLUMNS[0],
                f"未知关系类型: {rtype}"
            ))
            continue
        _check_endpoint(report, f, rel.source, idx, EDGE_COLUMNS[1], pk_to_labels)
        _check_endpoint(report, t, rel.target, idx, EDGE_COLUMNS[2], pk_to_labels)

    report.ok = not report.errors
    report.stats = stats
    return report

def _check_endpoint(
    report: ValidationReport, code: str, expect_label: str,
    row: int, column: str, pk_to_labels: dict[str, list[str]],
) -> None:
    labels = pk_to_labels.get(code)
    if not labels:
        report.warnings.append(Issue(
            "warning", "W8", "edges关系", row, column,
            f"{code} 不在本批数据中：若已在图谱中可忽略，入图时会再做一次图上校验"
        ))
    elif expect_label not in labels:
        report.errors.append(Issue(
            "error", "E8", "edges关系", row, column,
            f"端点 {code} 位于 {','.join(labels)} 表，但该关系要求实体类型为 {expect_label}"
        ))

def _is_number(v: Any) -> bool:
    if isinstance(v, (int, float)):
        return True
    try:
        float(str(v))
        return True
    except ValueError:
        return False
