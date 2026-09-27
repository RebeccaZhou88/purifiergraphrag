# @Author: RebeccaZhou
# @Description: Minimal Trie: longest-prefix matching over entity code tables, replacing hardcoded regex
#              极简 Trie（前缀树）：用实体编码表做最长匹配，替代硬编码正则。
"""

为什么不用正则：
- 客户编码规则千差万别（ERP 物料码、含斜杠/点号/中文），无法预先写正则
- 编码直接来自图谱本身，图里有什么就能匹配什么，新增实体零代码改动
- Trie 一次扫描 O(问句长度)，且天然支持"最长匹配优先"（FC-RO 与 FC-RO03 取后者）
"""
from __future__ import annotations

class Trie:
    __slots__ = ("_root",)

    def __init__(self) -> None:
        # key 节点: {"#": True} 表示一个词在此结束
        self._root: dict[str, dict] = {}

    def add(self, word: str) -> None:
        node = self._root
        for ch in word:
            node = node.setdefault(ch, {})
        node["#"] = {}

    def search_all(self, text: str) -> list[str]:
        """从每个位置出发做最长匹配，返回按出现顺序、去重后的命中词列表。"""
        hits: list[str] = []
        seen: set[str] = set()
        n = len(text)
        for i in range(n):
            node = self._root
            j = i
            last_end = -1
            while j < n:
                nxt = node.get(text[j])
                if nxt is None:
                    break
                node = nxt
                j += 1
                if "#" in node:
                    last_end = j
            if last_end > 0:
                w = text[i:last_end]
                if w not in seen:
                    seen.add(w)
                    hits.append(w)
        return hits

    def __len__(self) -> int:
        return len(self._root)
