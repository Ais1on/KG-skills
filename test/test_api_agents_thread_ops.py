from __future__ import annotations

import os
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import kg_agent.api.agents as agents_api
import kg_agent.app_state as app_state
import kg_agent.services.conversation as conversation_service
from kg_agent.services import init_conversation_db
from kg_agent.webapp import app


class _DummyRuntime:
    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.tools: list[object] = []
        self.dangerous_tools: set[str] = set()
        self.graph = object()

    def ask(self, message: str, thread_id: str = "default") -> str:
        return "dummy"


class TestAgentThreadApis(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp_root = Path("test/.tmp")
        cls._tmp_root.mkdir(parents=True, exist_ok=True)
        cls._db_path = cls._tmp_root / "conversations_agents.sqlite"
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

    def _create_agent(self, name: str = "thread-a") -> dict:
        original_build_agent_async = agents_api.build_agent_async

        async def _fake_build_agent_async(config):
            return _DummyRuntime()

        agents_api.build_agent_async = _fake_build_agent_async
        try:
            resp = self.client.post(
                "/api/agents",
                json={
                    "name": name,
                    "api_key_env": "DEEPSEEK_API_KEY",
                },
            )
        finally:
            agents_api.build_agent_async = original_build_agent_async

        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def test_patch_agent_name(self) -> None:
        created = self._create_agent(name="old-name")
        agent_id = created["agent_id"]

        resp = self.client.patch(f"/api/agents/{agent_id}", json={"name": "new-name"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["name"], "new-name")

        get_resp = self.client.get(f"/api/agents/{agent_id}")
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.json()["name"], "new-name")

    def test_patch_agent_name_empty(self) -> None:
        created = self._create_agent(name="old-name")
        agent_id = created["agent_id"]

        resp = self.client.patch(f"/api/agents/{agent_id}", json={"name": "   "})
        self.assertEqual(resp.status_code, 400)

    def test_delete_agent_with_purge_conversations(self) -> None:
        created = self._create_agent(name="thread-delete")
        agent_id = created["agent_id"]

        conv_resp = self.client.post(
            f"/api/agents/{agent_id}/conversations",
            json={"title": "session-a"},
        )
        self.assertEqual(conv_resp.status_code, 200)

        before = self.client.get(f"/api/v1/sessions?agent_id={agent_id}&limit=10&offset=0")
        self.assertEqual(before.status_code, 200)
        self.assertEqual(before.json()["total"], 1)

        delete_resp = self.client.delete(f"/api/agents/{agent_id}?purge_conversations=true")
        self.assertEqual(delete_resp.status_code, 200)
        body = delete_resp.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["purge_conversations"])
        self.assertEqual(body["deleted"]["conversations"], 1)

        after = self.client.get(f"/api/v1/sessions?agent_id={agent_id}&limit=10&offset=0")
        self.assertEqual(after.status_code, 200)
        self.assertEqual(after.json()["total"], 0)


if __name__ == "__main__":
    unittest.main()
