# @Author: RebeccaZhou
# @Description: Extraction prompts: unstructured after-sales docs -> knowledge graph triples
#              非结构化售后文档 → 知识图谱三元组的抽取 Prompt。
"""

设计要点（对应人工审核台的质量需求）：
1. 闭集抽取：只能产 Schema 内的实体/关系，关系白名单直接写进 prompt
2. 编码复用优先：把图里已有的编码表（codebook）喂给模型，文中明确提到的
   编码必须原样复用，禁止另造；只有全新实体才 code=null + temp_id
3. 证据留痕：每条关系必须带 evidence（原文连续片段），审核员一眼可核
4. 宁漏勿造：抽取不出来就留空，notes 说明；confidence < 0.6 审核台重点看
"""
from __future__ import annotations

import json

# 允许从文档中抽取的关系（文档域主要覆盖故障知识链，不含订单/客户）
DOC_RELATION_WHITELIST = (
    ("Model", "HAS_FAULT", "Fault"),
    ("Fault", "CAUSED_BY", "Cause"),
    ("Cause", "SOLVED_BY", "Solution"),
    ("Solution", "REQUIRES_FILTER", "Filter"),
    ("Model", "USES", "Filter"),
)

EXTRACT_SYSTEM = """你是一名净水器售后知识工程师，负责把维修手册、SOP、FAQ、工单文本
抽取为知识图谱三元组。只允许使用我给出的 Schema，禁止臆测。

【实体类型与字段】
- Fault 故障: code(编码,可空), symptom(一句话症状，必填)
- Cause 原因: code(可空), description(原因描述，必填)
- Solution 方案: code(可空), description(动宾短语方案，必填), cost(数字，可空)
- Model 型号 / Filter 滤芯: 只能引用 codebook 中已有编码，不得新建

【关系白名单】(源类型, 关系, 目标类型)
Model -[HAS_FAULT]-> Fault
Fault -[CAUSED_BY]-> Cause
Cause -[SOLVED_BY]-> Solution
Solution -[REQUIRES_FILTER]-> Filter
Model -[USES]-> Filter

【铁律】
1. 文中明确出现 codebook 里的编码时，必须原样引用，禁止改写或新造。
2. 全新的 Fault/Cause/Solution：code 填 null，并给一个临时 ID（new_1、new_2……）。
   关系端点引用新实体时写 "!temp:new_1"。
3. 每条关系必须附 evidence：原文中的连续片段（≤40字），用于人工核验；
   找不到原文依据的关系不要输出。
4. 只抽明确陈述的因果/方案，不要根据常识补全；拿不准的 confidence 给 0.5 以下。
5. 严格只输出一个 JSON 对象，不要 Markdown、不要解释，结构：
{
  "entities": {
    "Fault":    [{"temp_id": "new_1", "code": null, "symptom": "...", "confidence": 0.9}],
    "Cause":    [],
    "Solution": []
  },
  "relations": [
    {"type": "CAUSED_BY", "from_label": "Fault", "from": "FLT-001",
     "to_label": "Cause", "to": "!temp:new_2",
     "evidence": "原文连续片段", "confidence": 0.85}
  ],
  "notes": "抽取不确定或信息缺失的简要说明，没有则空字符串"
}"""

def build_codebook(codes_by_label: dict[str, list[str]], max_per_label: int = 200) -> str:
    """把已有编码表渲染成 prompt 片段（超长截断，防止 token 爆炸）。"""
    lines = []
    for label, codes in codes_by_label.items():
        if not codes:
            continue
        shown = codes[:max_per_label]
        more = f" 等 {len(codes)} 个" if len(codes) > max_per_label else ""
        lines.append(f"- {label}({len(codes)}): {', '.join(shown)}{more}")
    return "\n".join(lines) if lines else "（图谱中暂无编码，所有实体均为新实体）"

def extract_user(text: str, codebook: str, source_doc: str = "") -> str:
    return (
        f"【资料来源】{source_doc or '未标注'}\n"
        f"【图谱已有编码表】\n{codebook}\n\n"
        f"【待抽取文本】\n{text.strip()}\n\n"
        "请按系统消息的 JSON 结构输出抽取结果。"
    )

def safe_parse_json(text: str) -> dict:
    """宽容解析模型输出：去代码块围栏、截取首个 {...}。"""
    t = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(t)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(t[start:end + 1])
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                pass
    return {"entities": {}, "relations": [], "notes": f"模型输出无法解析: {t[:200]}"}
