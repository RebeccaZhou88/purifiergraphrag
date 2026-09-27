# @Author: RebeccaZhou
# @Description: Common Excel workbook read/write layer
#              Excel 工作簿读写公共层：
"""

- generate_workbook(): 按 registry 生成带说明/示例/下拉的模板
- parse_workbook():  把客户填好的工作簿解析成 {label: [{字段key: 值}, ...]}
"""
from __future__ import annotations

import io
from datetime import date, datetime
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .registry import EDGE_COLUMNS, NODE_SPECS, REL_SPECS, NodeSpec

_HEADER_FILL = PatternFill("solid", fgColor="D9EAD3")
_HEADER_FONT = Font(bold=True)
_META_FILL = PatternFill("solid", fgColor="FFF2CC")

def generate_workbook() -> bytes:
    """生成模板 xlsx，返回字节内容。"""
    wb = Workbook()
    wb.remove(wb.active)

    _build_readme(wb)
    for spec in NODE_SPECS:
        _build_node_sheet(wb, spec)
    _build_edges_sheet(wb)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

def _build_readme(wb: Workbook) -> None:
    ws = wb.create_sheet("说明", 0)
    lines = [
        ("PurifierGraph 数据导入模板", True),
        ("", False),
        ("1. 每个 sheet 对应一类实体，第一行是列头（请勿修改列头，可增删数据行）。", False),
        ("2. 黄色列为编码（主键），必须全局唯一；请直接沿用贵司 ERP/MES 中的现有编码。", False),
        ("3. 日期格式统一为 YYYY-MM-DD；带下拉的列只能选给定值。", False),
        ("4. 关系统一填在 edges 关系 sheet：源编码 → 关系类型 → 目标编码，编码必须已在对应实体 sheet 中存在。", False),
        ("5. 不需要的 sheet 可留空（仅保留列头）；示例行（灰色斜体）填写前请删除。", False),
        ("6. 支持增量导入：重复编码执行更新而非报错；不需要删除历史数据。", False),
        ("", False),
        ("关系类型清单：", True),
    ]
    for r in REL_SPECS:
        lines.append((f"  {r.source} —[{r.rtype}]→ {r.target}  （{r.desc}）", False))
    for i, (text, bold) in enumerate(lines, start=1):
        c = ws.cell(row=i, column=1, value=text)
        c.font = Font(bold=True, size=13) if bold else Font(size=11)
    ws.column_dimensions["A"].width = 100

def _build_node_sheet(wb: Workbook, spec: NodeSpec) -> None:
    ws = wb.create_sheet(spec.sheet)
    titles = spec.titles
    for col, fspec in enumerate(spec.fields, start=1):
        c = ws.cell(row=1, column=col, value=fspec.title)
        c.fill = _HEADER_FILL
        c.font = _HEADER_FONT
        c.alignment = Alignment(vertical="center")
        # 主键列用黄色提示
        if fspec.key == spec.pk:
            c.fill = _META_FILL
        # 列说明写批注（comment 需 Comment 对象，这里放第 2 行说明更直观，故用批注）
        from openpyxl.comments import Comment

        tip = fspec.desc or fspec.title
        if fspec.pattern:
            tip += f"\n格式: {fspec.pattern}"
        c.comment = Comment(tip, "ingest")
        ws.column_dimensions[get_column_letter(col)].width = max(14, len(fspec.title) * 2 + 8)

    # 枚举下拉
    for col, fspec in enumerate(spec.fields, start=1):
        if fspec.enum:
            dv = DataValidation(
                type="list",
                formula1='"' + ",".join(fspec.enum) + '"',
                allow_blank=not fspec.required,
                showErrorMessage=True,
            )
            dv.error = f"只能选: {', '.join(fspec.enum)}"
            dv.errorTitle = "枚举值不合法"
            ws.add_data_validation(dv)
            dv.add(f"{get_column_letter(col)}2:{get_column_letter(col)}5000")

    # 示例行（斜体灰色，提示客户删除）
    for ri, row in enumerate(spec.example_rows, start=2):
        for ci, fspec in enumerate(spec.fields, start=1):
            c = ws.cell(row=ri, column=ci, value=row.get(fspec.title))
            c.font = Font(italic=True, color="808080")
    ws.freeze_panes = "A2"

def _build_edges_sheet(wb: Workbook) -> None:
    ws = wb.create_sheet("edges关系")
    for col, title in enumerate(EDGE_COLUMNS, start=1):
        c = ws.cell(row=1, column=col, value=title)
        c.fill = _HEADER_FILL
        c.font = _HEADER_FONT
        ws.column_dimensions[get_column_letter(col)].width = 24
    rtypes = [r.rtype for r in REL_SPECS]
    dv = DataValidation(
        type="list",
        formula1='"' + ",".join(rtypes) + '"',
        showErrorMessage=True,
    )
    dv.error = "关系类型必须来自清单（见说明 sheet）"
    dv.errorTitle = "关系类型不合法"
    ws.add_data_validation(dv)
    dv.add("A2:A5000")
    examples = (
        ("USES", "PG-A100", "FC-RO03"),
        ("HAS_FAULT", "PG-A100", "FLT-001"),
        ("CAUSED_BY", "FLT-001", "CS-001"),
        ("SOLVED_BY", "CS-001", "SL-001"),
    )
    for ri, row in enumerate(examples, start=2):
        for ci, v in enumerate(row, start=1):
            c = ws.cell(row=ri, column=ci, value=v)
            c.font = Font(italic=True, color="808080")
    ws.freeze_panes = "A2"

# ============================================================
# 解析
# ============================================================

def _norm(v: Any) -> Any:
    if v is None:
        return ""
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v

def parse_workbook(data: bytes) -> dict[str, list[dict[str, Any]]]:
    """解析工作簿 → {label: 行列表}。

    - 按 sheet 名定位 NodeSpec（客户改名 sheet 会被忽略并在 errors 层面由调用方提示）
    - 列头按 registry 中文名映射回字段 key；无法识别的列忽略
    - 整行空白自动跳过
    - edges 固定以 "__edges__" 为 key
    """
    wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    out: dict[str, list[dict[str, Any]]] = {}

    for spec in NODE_SPECS:
        if spec.sheet not in wb.sheetnames:
            continue
        ws = wb[spec.sheet]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        header = [str(h).strip() if h is not None else "" for h in rows[0]]
        title2key = spec.title_to_key()
        # 列下标 → 字段 key
        colmap = {i: title2key[h] for i, h in enumerate(header) if h in title2key}
        records: list[dict[str, Any]] = []
        for raw in rows[1:]:
            rec: dict[str, Any] = {}
            for i, key in colmap.items():
                rec[key] = _norm(raw[i]) if i < len(raw) else ""
            # 主键为空视为空行（客户常误留空行）
            pk_val = str(rec.get(spec.pk, "")).strip()
            if not pk_val:
                continue
            rec[spec.pk] = pk_val
            # 字符串字段统一 strip
            for k, v in list(rec.items()):
                if isinstance(v, str):
                    rec[k] = v.strip()
            records.append(rec)
        out[spec.label] = records

    if "edges关系" in wb.sheetnames:
        ws = wb["edges关系"]
        rows = list(ws.iter_rows(values_only=True))
        edges: list[dict[str, str]] = []
        if rows:
            for raw in rows[1:]:
                vals = [(_norm(raw[i]) if i < len(raw) else "") for i in range(3)]
                vals = [str(v).strip() if v != "" else "" for v in vals]
                if not any(vals):
                    continue
                edges.append({"type": vals[0], "from": vals[1], "to": vals[2]})
        out["__edges__"] = edges

    wb.close()
    return out
