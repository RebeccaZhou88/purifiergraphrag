# @Author: RebeccaZhou
# @Description: Semantic Kernel builder: registers plugins and dependencies / Semantic Kernel
#              构建：注册 Plugin 与依赖。
"""

Semantic Kernel 构建：注册 Plugin 与依赖。

新版：SmartEntityCypherPlugin（规则优先 + LLM 回退），
      80%+ 常规查询零 LLM 调用，省 ~2.5s。
"""
from __future__ import annotations

from semantic_kernel import Kernel

from app.core.deps import get_neo4j_client
from app.llm.providers import get_provider
from app.plugins.cypher_query import CypherQueryPlugin
from app.plugins.smart_entity_cypher import SmartEntityCypherPlugin
from app.plugins.entity_cypher import EntityCypherPlugin
from app.plugins.graph_context import GraphContextPlugin
from app.plugins.llm_generation import LLMGenerationPlugin


def build_kernel(provider: str | None = None) -> Kernel:
    """构建 Kernel。provider 为 None 时用 settings.llm_provider（默认）。"""
    kernel = Kernel()

    llm = get_provider(provider)
    neo4j = get_neo4j_client()

    # 新版：规则优先 + LLM 回退（零 LLM 调用省延迟）
    kernel.add_plugin(SmartEntityCypherPlugin(llm), plugin_name="entity_cypher")
    # 旧版：纯 LLM 合并插件（保留，给回退用）
    kernel.add_plugin(EntityCypherPlugin(llm), plugin_name="entity_cypher_llm")
    # CypherQueryPlugin：execute（纯执行）+ query（生成+执行）
    kernel.add_plugin(CypherQueryPlugin(llm, neo4j), plugin_name="cypher")
    kernel.add_plugin(GraphContextPlugin(), plugin_name="context")
    kernel.add_plugin(LLMGenerationPlugin(llm), plugin_name="generator")
    return kernel
