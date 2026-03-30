from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from urllib import error, request

from langchain_core.tools import tool


def _parse_domain_list(raw: str) -> list[str]:
    value = raw.strip()
    if not value:
        return []

    data = json.loads(value)
    if not isinstance(data, list):
        raise ValueError("must be a JSON array")

    normalized: list[str] = []
    for item in data:
        if not isinstance(item, str):
            raise ValueError("all domain values must be strings")
        text = item.strip()
        if text:
            normalized.append(text)
    return normalized


@tool
def echo(text: str) -> str:
    """Echo any input text back to the caller."""
    return text


@tool
def utc_now() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


@tool
def tavily_search(
    query: str,
    max_results: int = 5,
    search_depth: str = "basic",
    topic: str = "general",
    include_answer: bool = True,
    include_raw_content: bool = False,
    include_images: bool = False,
    include_domains_json: str = "[]",
    exclude_domains_json: str = "[]",
) -> str:
    """Run Tavily real-time web search and return JSON results."""
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key:
        return json.dumps(
            {"ok": False, "error": "Missing TAVILY_API_KEY environment variable."},
            ensure_ascii=False,
        )

    text_query = query.strip()
    if not text_query:
        return json.dumps({"ok": False, "error": "query must not be empty"}, ensure_ascii=False)

    normalized_depth = search_depth.strip().lower()
    if normalized_depth not in {"basic", "advanced"}:
        return json.dumps(
            {"ok": False, "error": "search_depth must be one of: basic, advanced"},
            ensure_ascii=False,
        )

    normalized_topic = topic.strip().lower()
    if normalized_topic not in {"general", "news"}:
        return json.dumps(
            {"ok": False, "error": "topic must be one of: general, news"},
            ensure_ascii=False,
        )

    if max_results < 1 or max_results > 20:
        return json.dumps(
            {"ok": False, "error": "max_results must be between 1 and 20"},
            ensure_ascii=False,
        )

    try:
        include_domains = _parse_domain_list(include_domains_json)
        exclude_domains = _parse_domain_list(exclude_domains_json)
    except json.JSONDecodeError as exc:
        return json.dumps(
            {"ok": False, "error": f"Domain list is not valid JSON: {exc}"},
            ensure_ascii=False,
        )
    except ValueError as exc:
        return json.dumps(
            {"ok": False, "error": f"Invalid domain list: {exc}"},
            ensure_ascii=False,
        )

    payload = {
        "api_key": api_key,
        "query": text_query,
        "search_depth": normalized_depth,
        "topic": normalized_topic,
        "max_results": max_results,
        "include_answer": include_answer,
        "include_raw_content": include_raw_content,
        "include_images": include_images,
        "include_domains": include_domains,
        "exclude_domains": exclude_domains,
    }

    req = request.Request(
        url="https://api.tavily.com/search",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=30) as response:
            body = response.read().decode("utf-8")
            data = json.loads(body)
            return json.dumps({"ok": True, "data": data}, ensure_ascii=False)
    except error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            detail = str(exc)
        return json.dumps(
            {
                "ok": False,
                "error": "Tavily API returned an HTTP error",
                "status_code": exc.code,
                "detail": detail,
            },
            ensure_ascii=False,
        )
    except error.URLError as exc:
        return json.dumps(
            {
                "ok": False,
                "error": "Failed to connect Tavily API",
                "detail": str(exc.reason),
            },
            ensure_ascii=False,
        )
    except Exception as exc:  # pragma: no cover
        return json.dumps(
            {
                "ok": False,
                "error": "Unexpected Tavily search failure",
                "detail": str(exc),
            },
            ensure_ascii=False,
        )


TOOLS = [echo, utc_now, tavily_search]
