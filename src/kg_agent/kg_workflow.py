from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field


KG_KEYWORDS = (
    "知识图谱",
    "图谱",
    "实体",
    "关系",
    "三元组",
    "triplet",
    "triplets",
    "entity",
    "entities",
    "relation",
    "relations",
    "extract",
    "提取",
    "抽取",
)

SANDBOX_KEYWORDS = (
    "python",
    "代码",
    "code",
    "执行",
    "运行",
    "sandbox",
    "正则",
    "清洗",
    "normalize",
)

CODE_BLOCK_RE = re.compile(r"```(?:python)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


class GraphEntity(BaseModel):
    name: str = Field(min_length=1)
    type: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphTriplet(BaseModel):
    head: str = Field(min_length=1)
    relation: str = Field(min_length=1)
    tail: str = Field(min_length=1)
    properties: dict[str, Any] = Field(default_factory=dict)


class TextExtractionResult(BaseModel):
    entities: list[GraphEntity] = Field(default_factory=list)
    triplets: list[GraphTriplet] = Field(default_factory=list)
    sandbox_code: str = ""


def detect_workflow_mode(message_text: str) -> str:
    text = (message_text or "").strip()
    lowered = text.lower()

    if extract_python_code(text) and any(keyword in lowered for keyword in SANDBOX_KEYWORDS):
        return "code_sandbox"

    if any(keyword in lowered for keyword in KG_KEYWORDS):
        return "text_extraction_skill"

    return "assistant"


def extract_python_code(text: str) -> str:
    match = CODE_BLOCK_RE.search(text or "")
    if match is not None:
        return match.group(1).strip()
    return ""


def parse_json_object(text: str) -> dict[str, Any]:
    body = (text or "").strip()
    if not body:
        return {}

    candidates = [body]
    fenced = CODE_BLOCK_RE.search(body)
    if fenced is not None:
        candidates.insert(0, fenced.group(1).strip())

    loose = JSON_BLOCK_RE.search(body)
    if loose is not None:
        candidates.append(loose.group(0).strip())

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return {}


def _canonical_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.lower().startswith("cve-"):
        return text.upper()
    return text


def coerce_extraction_result(payload: dict[str, Any]) -> dict[str, Any]:
    data = TextExtractionResult.model_validate(payload)
    return {
        "entities": [
            {
                "name": _canonical_name(item.name),
                "type": item.type,
                "properties": dict(item.properties),
            }
            for item in data.entities
        ],
        "triplets": [
            {
                "head": _canonical_name(item.head),
                "relation": item.relation.strip(),
                "tail": _canonical_name(item.tail),
                "properties": dict(item.properties),
            }
            for item in data.triplets
        ],
        "sandbox_code": data.sandbox_code.strip(),
    }


def _entity_record(item: Any) -> dict[str, Any] | None:
    if isinstance(item, str):
        name = _canonical_name(item)
        if not name:
            return None
        return {"name": name, "properties": {}}

    if isinstance(item, dict):
        name = _canonical_name(item.get("name") or item.get("entity") or item.get("id"))
        if not name:
            return None
        properties = item.get("properties") if isinstance(item.get("properties"), dict) else {}
        record: dict[str, Any] = {"name": name, "properties": dict(properties)}
        item_type = item.get("type")
        if isinstance(item_type, str) and item_type.strip():
            record["type"] = item_type.strip()
        return record
    return None


def _triplet_record(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None

    head = _canonical_name(item.get("head"))
    relation = str(item.get("relation") or "").strip()
    tail = _canonical_name(item.get("tail"))
    if not head or not relation or not tail:
        return None

    properties = item.get("properties") if isinstance(item.get("properties"), dict) else {}
    return {
        "head": head,
        "relation": relation,
        "tail": tail,
        "properties": dict(properties),
    }


def normalize_graph_payload(payload: dict[str, Any]) -> dict[str, Any]:
    entities_in = payload.get("entities")
    triplets_in = payload.get("triplets")

    entities: list[dict[str, Any]] = []
    entities_seen: dict[str, int] = {}
    for item in entities_in if isinstance(entities_in, list) else []:
        record = _entity_record(item)
        if record is None:
            continue
        key = record["name"].casefold()
        existing_idx = entities_seen.get(key)
        if existing_idx is None:
            entities_seen[key] = len(entities)
            entities.append(record)
            continue
        current = entities[existing_idx]
        if not current.get("type") and record.get("type"):
            current["type"] = record["type"]
        merged = dict(current.get("properties") or {})
        merged.update(record.get("properties") or {})
        current["properties"] = merged

    triplets: list[dict[str, Any]] = []
    triplets_seen: set[tuple[str, str, str]] = set()
    for item in triplets_in if isinstance(triplets_in, list) else []:
        record = _triplet_record(item)
        if record is None:
            continue
        key = (record["head"].casefold(), record["relation"], record["tail"].casefold())
        if key in triplets_seen:
            continue
        triplets_seen.add(key)
        triplets.append(record)

    return {
        "entities": entities,
        "triplets": triplets,
        "sandbox_result": str(payload.get("sandbox_result") or "").strip(),
    }


def summarize_graph_payload(payload: dict[str, Any]) -> str:
    normalized = normalize_graph_payload(payload)
    entities = normalized["entities"]
    triplets = normalized["triplets"]
    sandbox_result = normalized["sandbox_result"]

    lines = [
        f"提取完成：实体 {len(entities)} 个，关系 {len(triplets)} 条。",
    ]

    if entities:
        names = ", ".join(item["name"] for item in entities[:8])
        lines.append(f"实体：{names}")

    if triplets:
        lines.append("关系：")
        for item in triplets[:8]:
            lines.append(f"- {item['head']} -[{item['relation']}]-> {item['tail']}")

    if sandbox_result:
        lines.append("沙箱结果：")
        lines.append(sandbox_result[:600])

    return "\n".join(lines)
