from __future__ import annotations

import asyncio
import os
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import kg_agent.api.agents as agents_api
import kg_agent.app_state as app_state
import kg_agent.graph as graph_module
import kg_agent.services.conversation as conversation_service
from kg_agent.services import conversation_record_turn, create_conversation, init_conversation_db, restore_persisted_agents_async
from kg_agent.webapp import app


class _DummyRuntime:
    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.tools: list[object] = []
        self.dangerous_tools: set[str] = set()
        self.graph = object()

    def ask(self, message: str, thread_id: str = "default") -> str:
        return "dummy"


class TestAgentPersistence(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp_root = Path("test/.tmp")
        cls._tmp_root.mkdir(parents=True, exist_ok=True)
        cls._db_path = cls._tmp_root / "agents_persistence.sqlite"
        if cls._db_path.exists():
            cls._db_path.unlink()

        app_state.CONV_DB_PATH = cls._db_path
        conversation_service.CONV_DB_PATH = cls._db_path
        init_conversation_db()
        os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            if cls._db_path.exists():
                cls._db_path.unlink()
        except Exception:
            pass

    def setUp(self) -> None:
        with app_state.AGENT_LOCK:
            app_state.AGENT_STORE.clear()

    def test_agent_and_conversation_restore_after_memory_clear(self) -> None:
        original_api_build_agent_async = agents_api.build_agent_async
        original_graph_build_agent_async = graph_module.build_agent_async

        async def _fake_build_agent_async(config):
            return _DummyRuntime()

        agents_api.build_agent_async = _fake_build_agent_async
        graph_module.build_agent_async = _fake_build_agent_async
        try:
            create_resp = self.client.post(
                "/api/agents",
                json={
                    "name": "persisted-agent",
                    "model": "deepseek-chat",
                },
            )
            self.assertEqual(create_resp.status_code, 200)
            created = create_resp.json()
            agent_id = created["agent_id"]

            conversation = create_conversation(agent_id, "持久化会话", None)
            conversation_record_turn(conversation["id"], "用户问题", "助手回答")

            with app_state.AGENT_LOCK:
                app_state.AGENT_STORE.clear()

            restored = asyncio.run(restore_persisted_agents_async())
            self.assertIn(agent_id, restored)

            list_resp = self.client.get(f"/api/agents/{agent_id}/conversations?limit=20&offset=0")
            self.assertEqual(list_resp.status_code, 200)
            items = list_resp.json()["items"]
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["id"], conversation["id"])

            messages_resp = self.client.get(
                f"/api/agents/{agent_id}/conversations/{conversation['id']}/messages?limit=20&offset=0"
            )
            self.assertEqual(messages_resp.status_code, 200)
            messages = messages_resp.json()["items"]
            self.assertEqual(len(messages), 2)
        finally:
            agents_api.build_agent_async = original_api_build_agent_async
            graph_module.build_agent_async = original_graph_build_agent_async


if __name__ == "__main__":
    unittest.main()
