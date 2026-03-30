---
name: ti-ioc-tool
description: 对 IOC 执行识别、校验、归一化、去重与质量打分，输出可入图指标和无效指标清单。
---

# TI IOC Tool

## 输入
```json
{
  "source_id": "string",
  "iocs": [],
  "entities": [],
  "options": {
    "drop_private_ip": true,
    "min_confidence": 0.6
  }
}
```

## 输出
```json
{
  "source_id": "string",
  "iocs": [],
  "invalid_iocs": [],
  "errors": []
}
```

## 支持类型
- `IP`、`Domain`、`URL`、`FileHash`、`Email`

## 处理规则
1. 先识别类型，再校验格式。
2. 归一化: `Domain/Email/Hash` 小写，URL 规范化协议和默认端口。
3. 去重主键: `type + normalized_value`。
4. 合并同值来源到 `observed_values[]`。

## 置信度
- 格式合法且上下文明确恶意: `0.80-0.95`
- 仅格式合法: `0.60-0.79`
- 不合法: 进入 `invalid_iocs[]`

## 过滤
- `is_valid=true` 且 `confidence>=min_confidence` 才建议入图。
- 内网 IP 可按 `drop_private_ip=true` 过滤。

## 失败处理
- 输入为空: 返回空结果并写 `errors[]`。
- 全部无效: 保留 `invalid_iocs[]`，不阻断后续流程。
