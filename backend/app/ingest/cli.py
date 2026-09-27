# @Author: RebeccaZhou
# @Description: ETL command-line entry (for scheduled tasks / ops scripts)
#              ETL 命令行入口（供定时任务运维脚本调用）。
"""

ETL 命令行入口（供定时任务 / 运维脚本调用）。

用法（在 backend/ 目录，PYTHONPATH=.）：
  python -m app.ingest.cli template -o template.xlsx
  python -m app.ingest.cli validate 客户数据.xlsx
  python -m app.ingest.cli load     客户数据.xlsx --source erp --retire-missing
  python -m app.ingest.cli extract  维修手册.txt --source-doc manual_v3.pdf
  python -m app.ingest.cli review-list --status pending
  python -m app.ingest.cli approve RV-20260924-000001
  python -m app.ingest.cli refresh-dict
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.core.config import settings
from app.graph.neo4j_client import Neo4jClient
from app.ingest.entity_dict import entity_dict
from app.ingest.extractor import DocExtractor
from app.ingest.loader import load_parsed, load_state
from app.ingest.review import review_store
from app.ingest.validator import validate_workbook
from app.ingest.workbook import generate_workbook


def _client() -> Neo4jClient:
    return Neo4jClient(
        uri=settings.neo4j_uri, user=settings.neo4j_user, password=settings.neo4j_password
    )


def _cmd_template(args: argparse.Namespace) -> None:
    Path(args.output).write_bytes(generate_workbook())
    print(f"模板已生成: {args.output}")


def _cmd_validate(args: argparse.Namespace) -> int:
    report, _ = validate_workbook(Path(args.file).read_bytes())
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 0 if report.ok else 1


async def _cmd_load(args: argparse.Namespace) -> int:
    report, parsed = validate_workbook(Path(args.file).read_bytes())
    if not report.ok:
        print(f"校验未通过（{len(report.errors)} 个错误），已阻止入图：", file=sys.stderr)
        for e in report.errors[:20]:
            print(f"  [{e.sheet} 行{e.row}] {e.message}", file=sys.stderr)
        return 1
    client = _client()
    try:
        result = await load_parsed(
            client, parsed, source=args.source, retire_missing=args.retire_missing
        )
        await entity_dict.load_from_graph(client)
    finally:
        await client.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


async def _cmd_extract(args: argparse.Namespace) -> None:
    text = Path(args.file).read_text(encoding="utf-8")
    item = await DocExtractor().extract_text(text, source_doc=args.source_doc)
    print(json.dumps(item, ensure_ascii=False, indent=2))
    print(f"已入审核队列: {item['id']}（pending）", file=sys.stderr)


def _cmd_review_list(args: argparse.Namespace) -> None:
    for item in review_store.list_items(status=args.status):
        n_ents = sum(len(v) for v in item.get("entities", {}).values())
        print(f"{item['id']}  {item['status']:8}  "
              f"实体{n_ents} 关系{len(item.get('relations', []))}  "
              f"{item['source_doc']}#chunk{item['chunk_index']}")
    print(review_store.counts(), file=sys.stderr)


async def _cmd_decide(args: argparse.Namespace) -> None:
    client = _client()
    try:
        item = await review_store.decide(client, args.id, args.action, args.comment or "")
    finally:
        await client.close()
    print(json.dumps(item.get("load_result", {"status": item["status"]}),
                     ensure_ascii=False, indent=2))


async def _cmd_refresh_dict(args: argparse.Namespace) -> None:
    client = _client()
    try:
        total = await entity_dict.load_from_graph(client)
    finally:
        await client.close()
    print(f"词典刷新完成: {total} 个编码")


def main() -> int:
    p = argparse.ArgumentParser(description="PurifierGraph ETL CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("template", help="生成 Excel 模板")
    t.add_argument("-o", "--output", default="purifiergraph_template.xlsx")
    t.set_defaults(func=lambda a: _cmd_template(a))

    v = sub.add_parser("validate", help="校验 Excel")
    v.add_argument("file")
    v.set_defaults(func=_cmd_validate)

    ld = sub.add_parser("load", help="校验并增量入图")
    ld.add_argument("file")
    ld.add_argument("--source", default="excel-cli")
    ld.add_argument("--retire-missing", action="store_true")
    ld.set_defaults(func=lambda a: asyncio.run(_cmd_load(a)))

    ex = sub.add_parser("extract", help="文档 LLM 抽取入审核队列")
    ex.add_argument("file")
    ex.add_argument("--source-doc", default="")
    ex.set_defaults(func=lambda a: asyncio.run(_cmd_extract(a)))

    rl = sub.add_parser("review-list", help="审核队列")
    rl.add_argument("--status", default="pending")
    rl.set_defaults(func=_cmd_review_list)

    ap = sub.add_parser("approve", help="审核通过并入图")
    ap.add_argument("id")
    ap.add_argument("--comment", default="")
    ap.set_defaults(func=lambda a: asyncio.run(_cmd_decide(
        argparse.Namespace(id=a.id, action="approve", comment=a.comment))))

    rj = sub.add_parser("reject", help="审核驳回")
    rj.add_argument("id")
    rj.add_argument("--comment", default="")
    rj.set_defaults(func=lambda a: asyncio.run(_cmd_decide(
        argparse.Namespace(id=a.id, action="reject", comment=a.comment))))

    rf = sub.add_parser("refresh-dict", help="刷新实体动态词典")
    rf.set_defaults(func=lambda a: asyncio.run(_cmd_refresh_dict(a)))

    args = p.parse_args()
    result = args.func(args)
    return result if isinstance(result, int) else 0


if __name__ == "__main__":
    raise SystemExit(main())
