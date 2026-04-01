from __future__ import annotations

import os
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import kg_agent.api.templates as templates_api
import kg_agent.app_state as app_state
import kg_agent.services.conversation as conversation_service
from kg_agent.services import create_tool_confirmation, init_conversation_db
from kg_agent.webapp import app


class _DummyRuntime:
    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.tools: list[object] = []
        self.dangerous_tools: set[str] = set()
        self.graph = object()

    def ask(self, message: str, thread_id: str = "default") -> str:
        return "dummy"


class TestM2M3Apis(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp_root = Path("test/.tmp")
        cls._tmp_root.mkdir(parents=True, exist_ok=True)
        cls._db_path = cls._tmp_root / "conversations.sqlite"
        if cls._db_path.exists():
            cls._db_path.unlink()

        # Route handlers import from conversation service module-level path,
        # so patch both holders to keep tests isolated.
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
        with app_state.TOOL_CONFIRM_LOCK:
            app_state.TOOL_CONFIRMATIONS.clear()

    def test_get_templates(self) -> None:
        resp = self.client.get("/api/v1/templates")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("items", data)
        self.assertGreaterEqual(data.get("total", 0), 1)

        first = data["items"][0]
        self.assertIn("id", first)
        self.assertIn("name", first)
        self.assertIn("system_prompt", first)
        self.assertIn("model_config", first)
        self.assertIn("tools_config", first)

    def test_create_agent_from_template(self) -> None:
        original_build_agent = templates_api.build_agent
        templates_api.build_agent = lambda config: _DummyRuntime()
        try:
            resp = self.client.post(
                "/api/v1/agents/from-template",
                json={
                    "template_id": "tpl-default",
                    "agent_name": "tpl-agent",
                    "session_title": "m2 session",
                },
            )
        finally:
            templates_api.build_agent = original_build_agent

        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertIn("agent", data)
        self.assertIn("session", data)
        agent_id = data["agent"]["agent_id"]
        self.assertTrue(agent_id)
        self.assertEqual(data["session"]["agent_id"], agent_id)
        self.assertEqual(data["session"]["title"], "m2 session")

        with app_state.AGENT_LOCK:
            self.assertIn(agent_id, app_state.AGENT_STORE)

    def test_confirm_tool_api(self) -> None:
        record = create_tool_confirmation(
            agent_id="agent-test",
            thread_id="thread-test",
            tool_name="drop_table",
            args={"table": "users"},
        )

        resp = self.client.post(
            "/api/v1/tools/confirm",
            json={"confirmation_id": record["id"], "approved": True},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["status"], "approved")
        self.assertTrue(data["approved"])

    def test_confirm_tool_not_found(self) -> None:
        resp = self.client.post(
            "/api/v1/tools/confirm",
            json={"confirmation_id": "missing-id", "approved": True},
        )
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
