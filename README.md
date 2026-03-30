# KG-skills

面向威胁情报知识图谱（Threat Intelligence KG）的 Agentic Skills 集合。

## 项目目标

将威胁情报输入（报告文本、IOC 列表、结构化 JSON）转换为可落库的知识图谱结果，支持以下流程：

1. 实体/关系/证据抽取
2. IOC 校验与归一化
3. Neo4j 映射与 Cypher 生成

## 目录结构

```text
skills/
  threat-intel-kg-agentic/   # 主控编排 skill（只负责调用与流程）
  ti-llm-extract/            # 抽取 skill（实体/关系/证据）
  ti-ioc-tool/               # IOC 处理 skill（校验/归一/去重）
  ti-neo4j-ingest/           # 入库 skill（Neo4j 映射/Cypher）
```

每个 skill 均包含：

- `SKILL.md`：能力说明与执行规范
- `agents/openai.yaml`：UI 元信息（显示名、简述、默认提示词）

## Skills 说明

### 1) `threat-intel-kg-agentic`

- 职责：流程编排，不承载具体业务规则。
- 调用顺序：`ti-llm-extract -> ti-ioc-tool -> ti-neo4j-ingest`
- 输出：聚合 `entities/relations/evidence/iocs/cypher/stats/errors`

### 2) `ti-llm-extract`

- 职责：从文本提取实体、关系和证据。
- 重点：本体白名单、证据绑定、关系有效性校验、置信度打分。

### 3) `ti-ioc-tool`

- 职责：IOC 类型识别、合法性校验、归一化、去重。
- 重点：输出 `iocs` 与 `invalid_iocs`，为入图提供质量控制。

### 4) `ti-neo4j-ingest`

- 职责：将结构化结果映射为 Neo4j 节点/关系并生成幂等 Cypher。
- 重点：约束建议、主键策略、低置信关系过滤、失败降级。

## 快速使用建议

1. 需要端到端执行时，优先触发 `threat-intel-kg-agentic`。
2. 仅做局部任务时，直接调用对应功能 skill：
   - 抽取：`ti-llm-extract`
   - IOC 清洗：`ti-ioc-tool`
   - 入库：`ti-neo4j-ingest`

## 设计原则

- 主控只编排，不下沉业务规则。
- 具体规则全部放到功能 skill，便于独立演进与测试。
- 输出结构尽量统一，降低跨阶段字段对接成本。


