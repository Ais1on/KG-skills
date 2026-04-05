from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kg_agent.config import AgentConfig

from kg_agent.checkpoints import build_redis_checkpointer


class _FakeRedisClient:
    last_url = ""
    ping_calls = 0

    @classmethod
    def from_url(cls, url: str, decode_responses: bool = False) -> "_FakeRedisClient":
        client = cls()
        client.url = url
        client.decode_responses = decode_responses
        cls.last_url = url
        return client

    def ping(self) -> None:
        type(self).ping_calls += 1


def _install_fake_redis_module(fake_saver_class: type) -> dict[str, types.ModuleType]:
    langgraph_module = types.ModuleType("langgraph")
    checkpoint_module = types.ModuleType("langgraph.checkpoint")
    redis_module = types.ModuleType("langgraph.checkpoint.redis")
    redis_client_module = types.ModuleType("redis")
    redis_module.RedisSaver = fake_saver_class
    redis_client_module.Redis = _FakeRedisClient
    return {
        "langgraph": langgraph_module,
        "langgraph.checkpoint": checkpoint_module,
        "langgraph.checkpoint.redis": redis_module,
        "redis": redis_client_module,
    }


class _FakeRedisSaver:
    instances: list["_FakeRedisSaver"] = []

    def __init__(self, redis_client: _FakeRedisClient, ttl=None) -> None:
        self.url = getattr(redis_client, "url", "")
        self.ttl = ttl
        self.setup_calls = 0
        _FakeRedisSaver.instances.append(self)

    def setup(self) -> None:
        self.setup_calls += 1


class _BrokenRedisSaver(_FakeRedisSaver):
    def setup(self) -> None:
        raise RuntimeError("redis unavailable")


class RedisCheckpointTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeRedisSaver.instances.clear()
        _FakeRedisClient.last_url = ""
        _FakeRedisClient.ping_calls = 0

    def test_missing_redis_url_is_rejected(self) -> None:
        config = AgentConfig(memory_backend="redis", redis_url="")

        with self.assertRaises(ValueError):
            build_redis_checkpointer(config)

    def test_builds_redis_saver_and_runs_setup(self) -> None:
        config = AgentConfig(
            memory_backend="redis",
            redis_url="redis://127.0.0.1:6379/0",
            redis_key_prefix="kg:test",
            redis_ttl_seconds=123,
        )

        with patch.dict(sys.modules, _install_fake_redis_module(_FakeRedisSaver)):
            saver = build_redis_checkpointer(config)

        self.assertIsInstance(saver, _FakeRedisSaver)
        self.assertEqual(saver.url, "redis://127.0.0.1:6379/0")
        self.assertEqual(saver.ttl, {"default_ttl": 3, "refresh_on_read": True})
        self.assertEqual(saver.setup_calls, 1)
        self.assertEqual(_FakeRedisClient.last_url, "redis://127.0.0.1:6379/0")
        self.assertEqual(_FakeRedisClient.ping_calls, 1)
        self.assertEqual(getattr(saver, "kg_key_prefix"), "kg:test")
        self.assertEqual(getattr(saver, "kg_ttl_seconds"), 123)

    def test_setup_failure_is_not_silently_downgraded(self) -> None:
        config = AgentConfig(memory_backend="redis", redis_url="redis://127.0.0.1:6379/0")

        with patch.dict(sys.modules, _install_fake_redis_module(_BrokenRedisSaver)):
            with self.assertRaises(RuntimeError):
                build_redis_checkpointer(config)


if __name__ == "__main__":
    unittest.main()
