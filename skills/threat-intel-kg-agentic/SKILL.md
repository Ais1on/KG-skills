---
name: threat-intel-kg-agentic
description: Agentic 编排威胁情报知识图谱构建流程。仅负责调用与流程控制，按顺序调用 ti-llm-extract、ti-ioc-tool、ti-neo4j-ingest 并聚合输出。
---

# Threat Intel KG Agentic

## 职责
- 编排，不承载业务细则。
- 识别输入类型并选择调用链。
- 汇总子技能输出并返回统一结果。

## 调用链
1. 调用 `ti-llm-extract` 抽取 `entities/relations/evidence`。
2. 调用 `ti-ioc-tool` 处理 IOC（可按 `options` 关闭）。
3. 调用 `ti-neo4j-ingest` 生成/执行 Cypher（可按 `options` 关闭）。

## 参数透传
- `options.min_confidence` -> `ti-llm-extract` 与 `ti-neo4j-ingest`
- `options.enable_ioc_normalization` -> `ti-ioc-tool`
- `options.enable_graph_ingest` -> `ti-neo4j-ingest`

## 输出骨架
```json
{
  "source_id": "string",
  "entities": [],
  "relations": [],
  "evidence": [],
  "iocs": [],
  "cypher": [],
  "stats": {
    "entities_total": 0,
    "relations_total": 0,
    "iocs_total": 0
  },
  "errors": []
}
```
