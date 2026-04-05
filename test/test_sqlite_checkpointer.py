from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kg_agent.config import AgentConfig
from kg_agent.graph import _build_checkpointer_async


class SqliteCheckpointerTests(unittest.TestCase):
    def test_sqlite_checkpointer_is_async_saver_instance(self) -> None:
        tmp_root = Path("test/.tmp")
        tmp_root.mkdir(parents=True, exist_ok=True)
        db_path = tmp_root / "checkpoint-test.sqlite"
        if db_path.exists():
            db_path.unlink()

        checkpointer = None
        try:
            checkpointer = asyncio.run(
                _build_checkpointer_async(
                    AgentConfig(memory_backend="sqlite", memory_path=str(db_path)),
                    warnings=[],
                )
            )
            self.assertEqual(type(checkpointer).__name__, "AsyncSqliteSaver")
            self.assertTrue(hasattr(checkpointer, "get_next_version"))
        finally:
            if checkpointer is not None:
                cm = getattr(checkpointer, "_kg_agent_context_manager", None)
                if cm is not None:
                    asyncio.run(cm.__aexit__(None, None, None))
                    cm = None
                conn = getattr(checkpointer, "conn", None)
                if conn is not None and getattr(conn, "_running", False):
                    asyncio.run(conn.close())
            db_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
