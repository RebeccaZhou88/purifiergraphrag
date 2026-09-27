# -*- coding: utf-8 -*-
# @Author: RebeccaZhou
# @Description: Three-model comparison via Foundry built-in RAG evaluators (LLM-judge, 1-5 score, Pass/Fail)
#              三模型对比评估 —— Foundry 内置 RAG 评估器（LLM-judge，1-5 分判 Pass/Fail）。
"""
 评估指标：
  builtin.relevance    回答是否切题                    需要 query, response
  builtin.groundedness 回答是否忠实检索上下文(防编造)   需要 query, response, context
  builtin.retrieval    检索 context 与问题是否相关      需要 query, context

每行携带全部性能/token/状态列，门户单条可见；数值聚合（P95 等）由本地 compare_models.py 产出。

运行（backend 目录，foundry 环境）：
    python scripts/run_foundry_eval.py --limit 3 --providers deepseek   # 小批量验证
    python scripts/run_foundry_eval.py                                  # 三模型全量 221 条
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
EVAL_DIR = BACKEND / "data" / "eval"

PROVIDERS = ["deepseek", "qwen", "azure_openai"]
EVAL_NAME = "purifiergraph-eval-builtin-v2"

# 数据集全部列（judge 只用 query/response/context；其余随行为全链路留档）
STR_COLS = ["id", "query", "response", "context", "ground_truth", "cypher",
            "status", "cypher_error"]
INT_COLS = ["retrieved_count", "total_latency_ms", "ttft_ms", "t_extract_cypher_ms",
            "t_cypher_exec_ms", "t_context_ms", "t_generate_ms",
            "prompt_tokens", "completion_tokens", "total_tokens"]

def load_items(provider: str, limit: int | None) -> list[dict]:
    """读本地 jsonl，保留全部列（judge 只映射 query/response/context）。"""
    path = EVAL_DIR / f"eval_data_{provider}.jsonl"
    if not path.exists():
        raise SystemExit(f"缺少 {path}，先跑: python scripts/generate_eval_data.py --provider {provider}")
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if limit:
        rows = rows[:limit]
    items: list[dict] = []
    for r in rows:
        item = {c: r.get(c, "") for c in STR_COLS}
        for c in INT_COLS:
            item[c] = int(r.get(c) or 0)
        item["metadata"] = r.get("metadata", {})
        items.append(item)
    return items

def load_env_key(key: str, default: str = "") -> str:
    """从 backend/.env 读指定键，去除引号。"""
    env_path = BACKEND / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return default

def load_deployment_name() -> str:
    """judge 模型部署名，从 .env 读，默认 gpt-4.1-mini。"""
    return load_env_key("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1-mini")

def load_foundry_endpoint() -> str:
    """Foundry 项目 endpoint，从 .env 读。"""
    ep = load_env_key("FOUNDRY_ENDPOINT")
    if not ep:
        raise SystemExit("缺少 FOUNDRY_ENDPOINT，请在 backend/.env 中配置")
    return ep

def load_tenant_id() -> str:
    """Entra ID 租户 ID，从 .env 读。"""
    tid = load_env_key("FOUNDRY_TENANT_ID")
    if not tid:
        raise SystemExit("缺少 FOUNDRY_TENANT_ID，请在 backend/.env 中配置")
    return tid

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--providers", default=",".join(PROVIDERS))
    ap.add_argument("--eval-id", default=None, help="复用已有 eval，跳过创建")
    args = ap.parse_args()
    providers = [p.strip() for p in args.providers.split(",") if p.strip()]

    ENDPOINT = load_foundry_endpoint()
    TENANT_ID = load_tenant_id()
    judge_deployment = load_deployment_name()

    from azure.ai.projects import AIProjectClient
    from azure.identity import DeviceCodeCredential

    def _prompt(verification_uri, user_code, expires_on):
        print("\n" + "=" * 60)
        print(f"请登录：{verification_uri}  代码：{user_code}")
        print("=" * 60 + "\n", flush=True)

    cred = DeviceCodeCredential(tenant_id=TENANT_ID, prompt_callback=_prompt)
    cred.get_token("https://ai.azure.com/.default")
    print("登录成功")

    project = AIProjectClient(endpoint=ENDPOINT, credential=cred, allow_preview=True)
    client = project.get_openai_client()
    print(f"已连接 Foundry Project；judge 模型 = {judge_deployment}")

    item_properties = {c: {"type": "string"} for c in STR_COLS}
    item_properties.update({c: {"type": "integer"} for c in INT_COLS})
    item_properties["metadata"] = {"type": "object"}

    if args.eval_id:
        eval_id = args.eval_id
        print(f"复用 eval: {eval_id}")
    else:
        init_params = {"deployment_name": judge_deployment}
        eval_obj = client.evals.create(
            name=EVAL_NAME,
            data_source_config={
                "type": "custom",
                "item_schema": {"type": "object", "properties": item_properties},
            },
            testing_criteria=[
                {
                    "type": "azure_ai_evaluator",
                    "name": "relevance",
                    "evaluator_name": "builtin.relevance",
                    "initialization_parameters": init_params,
                    "data_mapping": {
                        "query": "{{item.query}}",
                        "response": "{{item.response}}",
                    },
                },
                {
                    "type": "azure_ai_evaluator",
                    "name": "groundedness",
                    "evaluator_name": "builtin.groundedness",
                    "initialization_parameters": init_params,
                    "data_mapping": {
                        "query": "{{item.query}}",
                        "response": "{{item.response}}",
                        "context": "{{item.context}}",
                    },
                },
                {
                    "type": "azure_ai_evaluator",
                    "name": "retrieval",
                    "evaluator_name": "builtin.retrieval",
                    "initialization_parameters": init_params,
                    "data_mapping": {
                        "query": "{{item.query}}",
                        "context": "{{item.context}}",
                    },
                },
            ],
        )
        eval_id = eval_obj.id
        print(f"eval 已创建: {eval_id}（{EVAL_NAME}）")

    # 提交 run；total=0 的基础设施失败（ACA 502）自动重试最多 3 次
    final_runs: dict[str, object] = {}
    for provider in providers:
        items = load_items(provider, args.limit)
        run = None
        for attempt in range(1, 4):
            run = client.evals.runs.create(
                eval_id=eval_id,
                name=f"{EVAL_NAME}-{provider}-a{attempt}",
                data_source={"type": "jsonl", "source": {"type": "file_content", "content": items}},
            )
            run_id = run.id
            print(f"run 已提交 [{provider}] 第{attempt}次: {run_id}（{len(items)} 条）")
            while True:
                run = client.evals.runs.retrieve(eval_id=eval_id, run_id=run_id)
                if run.status in ("completed", "failed", "canceled"):
                    break
                time.sleep(15)
            counts = getattr(run, "result_counts", None)
            total = getattr(counts, "total", None) or 0
            print(f"[{provider}] {run.status}  total={total}  counts={counts}")
            if run.status == "failed" and total == 0 and attempt < 3:
                print("  疑似基础设施失败（ACA 502/容器启动），30s 后重试...")
                time.sleep(30)
                continue
            break
        final_runs[provider] = run

    print("\n===== 对比汇总 =====")
    for provider, run in final_runs.items():
        counts = getattr(run, "result_counts", None)
        url = getattr(run, "report_url", None) or ""
        print(f"{provider:<14} status={run.status:<10} counts={counts}\n  {url}")

    print(f"\n到门户查看: Evaluations → {EVAL_NAME} → Compare runs")

if __name__ == "__main__":
    main()
