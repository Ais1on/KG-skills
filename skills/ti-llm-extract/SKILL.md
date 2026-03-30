---
name: ti-llm-extract
description: 从威胁情报文本中抽取实体、关系与证据，输出可入图的标准化 JSON。用于报告抽取、告警文本结构化、关系证据化场景。
---

# TI LLM Extract

## 输入
```json
{
  "source_id": "string",
  "text": "string",
  "options": {"min_confidence": 0.6}
}
```

## 输出
```json
{
  "source_id": "string",
  "entities": [],
  "relations": [],
  "evidence": [],
  "errors": []
}
```

## 白名单
- 实体: `ThreatActor|Malware|Campaign|Vulnerability|Tool|IP|Domain|URL|FileHash|Email|Organization|Person|Location|TTP|Report`
- 关系: `USES|TARGETS|ATTRIBUTED_TO|EXPLOITS|INDICATES|COMMUNICATES_WITH|HOSTS|DELIVERS|ASSOCIATED_WITH|RELATED_TO`

## 抽取规则
1. 只输出有文本证据支持的实体和关系。
2. 每条关系必须绑定至少一条 `evidence_ids`。
3. `relations.from/to` 必须能定位到 `entities.id`。
4. 时间统一 `YYYY-MM-DD`，未知用 `null`。

## 归一化与消歧
- CVE 统一 `CVE-YYYY-NNNN+`。
- TTP 统一 `T####` 或 `T####.###`。
- 同类型同规范值优先合并，别名写入 `aliases[]`。

## 置信度
- 明确事实陈述: `0.80-0.95`
- 弱关联: `0.55-0.79`
- 无直接证据: 不输出关系

## 失败处理
- 文本无有效信息: 返回空结构并写 `errors[]`。
- 字段解析失败: 保留可解析部分并记录错误。
