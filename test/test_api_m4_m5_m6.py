from __future__ import annotations

import asyncio
import os
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import kg_agent.api.memory as memory_api
import kg_agent.api.sandbox as sandbox_api
import kg_agent.app_state as app_state
import kg_agent.services.conversation as conversation_service
import kg_agent.services.memory as memory_service
from kg_agent.services import conversation_record_turn, init_conversation_db, run_memory_job, stream_agent_events
from kg_agent.webapp import app


class _FakeGraph:
    async def astream_events(self, payload, config=None, version=None):
        yield {"event": "on_chain_start", "name": "assistant", "data": {"input": {"message": "hi"}}}
        yield {
            "event": "on_chat_model_stream",
            "name": "chat_model",
            "data": {"chunk": type("Chunk", (), {"content": "ok", "tool_call_chunks": [], "additional_kwargs": {}})()},
        }
        yield {"event": "on_chain_end", "name": "assistant", "data": {}}


_FakeSqliteSaver = type("SqliteSaver", (), {})
_FakeSqliteSaver.__module__ = "langgraph.checkpoint.sqlite"


class _FakeSyncGraph:
    async def astream_events(self, payload, config=None, version=None):
        raise AssertionError("sqlite saver path should use sync stream_events")

    def stream_events(self, payload, config=None, version=None):
        yield {"event": "on_chain_start", "name": "assistant", "data": {"input": {"message": "hi"}}}
        yield {
            "event": "on_chat_model_stream",
            "name": "chat_model",
            "data": {"chunk": type("Chunk", (), {"content": "ok-sync", "tool_call_chunks": [], "additional_kwargs": {}})()},
        }
        yield {"event": "on_chain_end", "name": "assistant", "data": {}}


class _FakeRuntime:
    def __init__(self) -> None:
        self.graph = _FakeGraph()


class _FakeSyncRuntime:
    def __init__(self) -> None:
        self.graph = _FakeSyncGraph()
        self._checkpointer = _FakeSqliteSaver()


class _FakeItem:
    def __init__(self) -> None:
        self.runtime = _FakeRuntime()


class _FakeSyncItem:
    def __init__(self) -> None:
        self.runtime = _FakeSyncRuntime()


class TestM4M5M6Apis(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp_root = Path("test/.tmp")
        cls._tmp_root.mkdir(parents=True, exist_ok=True)
        cls._db_path = cls._tmp_root / "conversations_m456.sqlite"
        if cls._db_path.exists():
            cls._db_path.unlink()

        app_state.CONV_DB_PATH = cls._db_path
        conversation_service.CONV_DB_PATH = cls._db_path
        memory_service.CONV_DB_PATH = cls._db_path

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

    def test_m4_stream_emits_orchestration(self) -> None:
        async def _collect() -> list[dict]:
            events = []
            async for evt in stream_agent_events(_FakeItem(), "hello", "thread-test"):
                events.append(evt)
            return events

        rows = asyncio.run(_collect())
        names = [row.get("event") for row in rows]
        self.assertIn("orchestration", names)

    def test_m4_sqlite_stream_uses_sync_events(self) -> None:
        async def _collect() -> list[dict]:
            events = []
            async for evt in stream_agent_events(_FakeSyncItem(), "hello", "thread-test"):
                events.append(evt)
            return events

        rows = asyncio.run(_collect())
        names = [row.get("event") for row in rows]
        self.assertIn("token", names)
        self.assertIn("orchestration", names)

    def test_m5_memory_summarize(self) -> None:
        async def _fake_enqueue(job_id: str) -> str:
            return f"memory:{job_id}"

        original_enqueue = memory_api.enqueue_memory_job_arq
        memory_api.enqueue_memory_job_arq = _fake_enqueue
        try:
            create_resp = self.client.post(
                "/api/v1/sessions",
                json={"agent_id": "agent-m5", "title": "m5-session"},
            )
            self.assertEqual(create_resp.status_code, 200)
            session_id = create_resp.json()["id"]

            conversation_record_turn(session_id, "用户问题A", "助手回答A")
            conversation_record_turn(session_id, "用户问题B", "助手回答B")

            summarize_resp = self.client.post(
                f"/api/v1/sessions/{session_id}/memory/summarize",
                json={"max_messages": 10},
            )
            self.assertEqual(summarize_resp.status_code, 202)
            job_id = summarize_resp.json()["job_id"]

            run_memory_job(job_id)

            job_resp = self.client.get(f"/api/v1/memory/jobs/{job_id}")
            self.assertEqual(job_resp.status_code, 200)
            self.assertEqual(job_resp.json()["status"], "done")

            mem_resp = self.client.get(f"/api/v1/sessions/{session_id}/memories?limit=10&offset=0")
            self.assertEqual(mem_resp.status_code, 200)
            self.assertGreaterEqual(mem_resp.json()["total"], 1)
        finally:
            memory_api.enqueue_memory_job_arq = original_enqueue

    def test_m6_sandbox_execute(self) -> None:
        original_execute = sandbox_api.execute_sandbox_code
        sandbox_api.execute_sandbox_code = lambda language, code, timeout_sec: {
            "stdout": "hello sandbox\n",
            "stderr": "",
            "exit_code": 0,
            "execution_time_ms": 10,
            "runtime": "docker",
        }
        try:
            resp = self.client.post(
                "/api/v1/sandbox/execute",
                json={
                    "session_id": "session-test",
                    "language": "python",
                    "code": "print('hello sandbox')",
                    "timeout_sec": 5,
                },
            )
        finally:
            sandbox_api.execute_sandbox_code = original_execute

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["language"], "python")
        self.assertIn("execution_time_ms", body)
        self.assertIn("exit_code", body)
        self.assertEqual(body["runtime"], "docker")


if __name__ == "__main__":
    unittest.main()
