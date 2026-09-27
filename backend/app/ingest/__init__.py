# @Author: RebeccaZhou
# @Description: Production data ingestion (ETL) package
#              生产数据接入（ETL）包：
"""

- registry:  图谱 Schema 注册表（实体字段/主键/枚举/关系），模板、校验、入图的单一数据源
- template:  Excel 模板生成器（发给客户填写）
- validator: 回收文件校验器（必填/枚举/正则/重复/悬空边）
- loader:    增量入图加载器（MERGE upsert + 批次水位线 + 软删除）
- extractor: 非结构化文档 LLM 抽取（产出审核队列记录）
- review:    人工审核队列（JSONL 持久化，approved 后入图）
- entity_dict: 从图里动态加载实体编码表，供 rules.py 替换硬编码正则
"""
