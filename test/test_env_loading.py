from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kg_agent.services.common import load_dotenv


class EnvLoadingTests(unittest.TestCase):
    def test_load_dotenv_resolves_repo_relative_path_outside_cwd(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        tmp_root = repo_root / "test" / ".tmp"
        tmp_root.mkdir(parents=True, exist_ok=True)
        env_path = tmp_root / "repo-relative.env"
        env_key = "KG_TEST_REPO_RELATIVE_ENV"
        env_path.write_text(f"{env_key}=loaded\n", encoding="utf-8")

        previous = os.environ.get(env_key)
        original_cwd = Path.cwd()
        try:
            os.environ.pop(env_key, None)
            os.chdir(repo_root.parent)
            load_dotenv("test/.tmp/repo-relative.env")
            self.assertEqual(os.environ.get(env_key), "loaded")
        finally:
            os.chdir(original_cwd)
            env_path.unlink(missing_ok=True)
            if previous is None:
                os.environ.pop(env_key, None)
            else:
                os.environ[env_key] = previous


if __name__ == "__main__":
    unittest.main()
