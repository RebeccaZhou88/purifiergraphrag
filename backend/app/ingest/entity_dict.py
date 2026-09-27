# @Author: RebeccaZhou
# @Description: Dynamic entity-code dictionary: loads code tables from Neo4j, matches questions via Trie
#              实体编码动态词典：从 Neo4j 实时加载编码表，用 Trie 做问句匹配。
"""

替代 rules.py 里写死的 ENTITY_PATTERNS 正则：
- 图谱里新增了客户真实编码（如 ERP 物料码 XJ-RO/2024-08），无需改正则、无需重启
- 应用启动时 load_from_graph()；入图批次完成 / 审核通过后调 refresh()
- TTL 过期后由 API 层触发后台刷新；同步的规则引擎永远读快照，无锁无阻塞
- 图不可用或未加载时，rules.py 自动回退到内置正则 + seed 症状表
"""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from loguru import logger

from .registry import PK_BY_LABEL
from .trie import Trie

if TYPE_CHECKING:
    from ..graph.neo4j_client import Neo4jClient

# 症状归一化停用词（与原 rules.py 保持一致）
SYMPTOM_STOPWORDS = ("明显", "严重", "比较", "非常", "有点", "有些", "突然", "总是", "一直")

_DEFAULT_TTL = 300.0  # 快照 5 分钟过期

class EntityDictionary:
    def __init__(self, ttl: float = _DEFAULT_TTL) -> None:
        self._ttl = ttl
        self._tries: dict[str, Trie] = {}
        self._lc_map: dict[str, dict[str, str]] = {}   # label: {小写编码: 原编码}
        self._symptom_trie = Trie()
        self._symptom_codes: dict[str, list[str]] = {}  # 小写症状 → [故障编码]
        self.loaded: bool = False
        self.loaded_at: float = 0.0
        self.code_count: int = 0
        self.symptom_count: int = 0
        self._lock = asyncio.Lock()

    def is_ready(self) -> bool:
        return self.loaded

    def age(self) -> float:
        return time.time() - self.loaded_at if self.loaded else float("inf")

    def is_stale(self) -> bool:
        return self.age() > self._ttl

    async def load_from_graph(self, client: Neo4jClient) -> int:
        """从图里全量拉取实体编码 + 故障症状，重建内存快照。返回编码总数。"""
        async with self._lock:
            tries: dict[str, Trie] = {}
            lc_maps: dict[str, dict[str, str]] = {}
            total = 0
            for label, pk in PK_BY_LABEL.items():
                rows = await client.run(
                    f"MATCH (n:{label}) "
                    f"WHERE n.{pk} IS NOT NULL "
                    f"AND (n._lifecycle IS NULL OR n._lifecycle = 'active') "
                    f"RETURN n.{pk} AS v"
                )
                values = sorted({str(r["v"]) for r in rows if r["v"]})
                trie = Trie()
                lc: dict[str, str] = {}
                for v in values:
                    low = v.lower()
                    trie.add(low)
                    lc[low] = v
                tries[label] = trie
                lc_maps[label] = lc
                total += len(values)

            # 故障症状（症状文本 → 编码），供故障问句精确定位
            srows = await client.run(
                "MATCH (f:Fault) WHERE f.symptom IS NOT NULL "
                "AND (f._lifecycle IS NULL OR f._lifecycle = 'active') "
                "RETURN f.code AS code, f.symptom AS symptom"
            )
            strie = Trie()
            scodes: dict[str, list[str]] = {}
            for r in srows:
                sym, code = str(r["symptom"]), str(r["code"])
                low = sym.lower()
                strie.add(low)
                scodes.setdefault(low, [])
                if code not in scodes[low]:
                    scodes[low].append(code)

            # 一次性切换快照（规则引擎读到的永远是完整状态）
            self._tries, self._lc_map = tries, lc_maps
            self._symptom_trie, self._symptom_codes = strie, scodes
            self.loaded = True
            self.loaded_at = time.time()
            self.code_count = total
            self.symptom_count = len(scodes)
            logger.info(f"实体词典已从图谱加载: {total} 个编码 / {len(scodes)} 个症状")
            return total

    def extract(self, question: str) -> dict[str, list[str]]:
        """在问句中扫描各类型实体编码（忽略大小写，去重保序）。"""
        if not self.loaded:
            return {}
        q = question.lower()
        result: dict[str, list[str]] = {}
        for label, trie in self._tries.items():
            lc_hits = trie.search_all(q)
            if lc_hits:
                mapping = self._lc_map[label]
                result[label] = list(dict.fromkeys(mapping[h] for h in lc_hits))
        return result

    def codes(self, label: str) -> list[str]:
        """某类型的全部编码（供抽取 prompt 的 codebook）。"""
        return sorted(self._lc_map.get(label, {}).values()) if self.loaded else []

    def find_faults(self, question: str) -> list[str]:
        """问句包含故障症状（忽略程度副词）→ 故障编码列表。"""
        if not self.loaded or self.symptom_count == 0:
            return []
        q = question
        for w in SYMPTOM_STOPWORDS:
            q = q.replace(w, "")
        q = q.lower()
        codes: list[str] = []
        for low_sym in self._symptom_trie.search_all(q):
            for c in self._symptom_codes.get(low_sym, []):
                if c not in codes:
                    codes.append(c)
        return codes

    def status(self) -> dict:
        return {
            "loaded": self.loaded,
            "loaded_at": self.loaded_at,
            "age_seconds": round(self.age(), 1) if self.loaded else None,
            "stale": self.is_stale(),
            "code_count": self.code_count,
            "symptom_count": self.symptom_count,
            "counts_by_label": (
                {label: len(m) for label, m in self._lc_map.items()} if self.loaded else {}
            ),
        }

# 进程级单例
entity_dict = EntityDictionary()
