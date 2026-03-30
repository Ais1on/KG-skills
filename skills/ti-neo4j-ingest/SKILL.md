---
name: ti-neo4j-ingest
description: 将结构化威胁情报数据（entities/relations/evidence/iocs）映射并写入 Neo4j，生成幂等 Cypher 与约束建议。
---

# TI Neo4j Ingest

## 输入
```json
{
  "source_id": "string",
  "entities": [],
  "relations": [],
  "evidence": [],
  "iocs": [],
  "options": {
    "min_confidence": 0.6,
    "enable_graph_ingest": true
  }
}
```

## 映射
- 节点: `ThreatActor|Malware|Campaign|Vulnerability|Tool|IP|Domain|URL|FileHash|Email|Organization|Person|Location|TTP|Report|Evidence`
- 关系: `USES|TARGETS|ATTRIBUTED_TO|EXPLOITS|INDICATES|COMMUNICATES_WITH|HOSTS|DELIVERS|ASSOCIATED_WITH|RELATED_TO|SUPPORTED_BY_EVIDENCE`

## 主键
- IOC: `normalized_value`
- Vulnerability/TTP: `name`
- 其他: `normalized`，缺失时 `name`

## 约束模板
```cypher
CREATE CONSTRAINT ioc_ip IF NOT EXISTS FOR (n:IP) REQUIRE n.normalized_value IS UNIQUE;
CREATE CONSTRAINT ioc_domain IF NOT EXISTS FOR (n:Domain) REQUIRE n.normalized_value IS UNIQUE;
CREATE CONSTRAINT ioc_url IF NOT EXISTS FOR (n:URL) REQUIRE n.normalized_value IS UNIQUE;
CREATE CONSTRAINT ioc_hash IF NOT EXISTS FOR (n:FileHash) REQUIRE n.normalized_value IS UNIQUE;
CREATE CONSTRAINT vuln_cve IF NOT EXISTS FOR (n:Vulnerability) REQUIRE n.name IS UNIQUE;
```

## 写入流程
1. `MERGE` 节点。
2. 过滤低置信关系后 `MERGE` 关系。
3. 写入 `Evidence` 并建立证据连接。

## 输出
```json
{
  "source_id": "string",
  "cypher": [],
  "ingest_stats": {
    "nodes_merged": 0,
    "rels_merged": 0,
    "evidence_merged": 0
  },
  "errors": []
}
```

## 失败处理
- DB 不可达: 返回 `cypher[]`。
- 悬空关系: 丢弃并记录错误。
