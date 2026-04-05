from __future__ import annotations

import textwrap
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kg_agent.config import load_config
from kg_agent.schemas import AgentCreatePayload


class RedisConfigTests(unittest.TestCase):
    def test_load_config_reads_redis_fields(self) -> None:
        tmp_root = Path("test/.tmp")
        tmp_root.mkdir(parents=True, exist_ok=True)
        config_path = tmp_root / "redis-agent.yaml"
        config_path.write_text(
            textwrap.dedent(
                """
                memory_backend: redis
                redis_url: redis://127.0.0.1:6379/0
                redis_key_prefix: kg:langgraph:checkpoint
                redis_ttl_seconds: 600
                """
            ).strip(),
            encoding="utf-8",
        )

        try:
            config = load_config(config_path)
        finally:
            config_path.unlink(missing_ok=True)

        self.assertEqual(config.memory_backend, "redis")
        self.assertEqual(config.redis_url, "redis://127.0.0.1:6379/0")
        self.assertEqual(config.redis_key_prefix, "kg:langgraph:checkpoint")
        self.assertEqual(config.redis_ttl_seconds, 600)

    def test_agent_create_payload_accepts_redis_fields(self) -> None:
        payload = AgentCreatePayload(
            name="redis-agent",
            memory_backend="redis",
            redis_url="redis://127.0.0.1:6379/0",
            redis_key_prefix="kg:threads",
            redis_ttl_seconds=900,
        )

        self.assertEqual(payload.redis_url, "redis://127.0.0.1:6379/0")
        self.assertEqual(payload.redis_key_prefix, "kg:threads")
        self.assertEqual(payload.redis_ttl_seconds, 900)


if __name__ == "__main__":
    unittest.main()
