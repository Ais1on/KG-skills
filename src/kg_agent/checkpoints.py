from __future__ import annotations

import math
from typing import Any

from .config import AgentConfig


def _checkpoint_namespace(prefix: str, current: Any) -> str:
    resolved_prefix = prefix.strip()
    existing = str(current or "").strip()
    if not resolved_prefix:
        return existing
    if existing == resolved_prefix or existing.startswith(f"{resolved_prefix}:"):
        return existing
    if existing:
        return f"{resolved_prefix}:{existing}"
    return resolved_prefix


def _map_checkpoint_config(config: Any, key_prefix: str) -> Any:
    if not isinstance(config, dict):
        return config

    configurable = config.get("configurable")
    if not isinstance(configurable, dict):
        return config

    mapped = dict(config)
    mapped_configurable = dict(configurable)
    mapped_configurable["checkpoint_ns"] = _checkpoint_namespace(key_prefix, mapped_configurable.get("checkpoint_ns"))
    mapped["configurable"] = mapped_configurable
    return mapped


def _decorate_redis_saver(saver: Any, key_prefix: str) -> Any:
    sync_methods = ("get", "get_tuple", "list", "put", "put_writes")
    async_methods = ("aget", "aget_tuple", "alist", "aput", "aput_writes")

    for method_name in sync_methods:
        original = getattr(saver, method_name, None)
        if not callable(original):
            continue

        def _wrapped(config: Any, *args: Any, __original: Any = original, **kwargs: Any) -> Any:
            return __original(_map_checkpoint_config(config, key_prefix), *args, **kwargs)

        setattr(saver, method_name, _wrapped)

    for method_name in async_methods:
        original = getattr(saver, method_name, None)
        if not callable(original):
            continue

        async def _wrapped_async(config: Any, *args: Any, __original: Any = original, **kwargs: Any) -> Any:
            return await __original(_map_checkpoint_config(config, key_prefix), *args, **kwargs)

        setattr(saver, method_name, _wrapped_async)

    setattr(saver, "kg_key_prefix", key_prefix)
    return saver


def _redis_ttl_config(ttl_seconds: int) -> dict[str, Any] | None:
    if ttl_seconds <= 0:
        return None
    ttl_minutes = max(1, math.ceil(ttl_seconds / 60))
    return {"default_ttl": ttl_minutes, "refresh_on_read": True}


def build_redis_checkpointer(config: AgentConfig) -> Any:
    redis_url = (config.redis_url or "").strip()
    if not redis_url:
        raise ValueError("redis_url is required when memory_backend=redis")

    try:
        from redis import Redis
    except Exception as exc:  # pragma: no cover
        raise ImportError("Redis backend requires the 'redis' package.") from exc

    try:
        from langgraph.checkpoint.redis import RedisSaver
    except Exception as exc:  # pragma: no cover
        raise ImportError(
            "Redis checkpoint backend is unavailable. Install langgraph-checkpoint-redis and retry."
        ) from exc

    ttl_config = _redis_ttl_config(int(config.redis_ttl_seconds or 0))
    client = Redis.from_url(redis_url, decode_responses=False)
    client.ping()

    saver_kwargs: dict[str, Any] = {"redis_client": client}
    if ttl_config is not None:
        saver_kwargs["ttl"] = ttl_config

    saver = RedisSaver(**saver_kwargs)
    saver = _decorate_redis_saver(saver, (config.redis_key_prefix or "").strip())
    setattr(saver, "kg_ttl_seconds", int(config.redis_ttl_seconds or 0))

    setup = getattr(saver, "setup", None)
    if callable(setup):
        setup()

    return saver
