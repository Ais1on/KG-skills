from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kg_agent.graph import _forced_tavily_tool_call, _requires_tavily_search
from kg_agent.services.stream import _raw_event_to_sse


class SearchGateTests(unittest.TestCase):
    def test_requires_tavily_search_for_latest_vulnerability_queries(self) -> None:
        self.assertTrue(_requires_tavily_search("查询一下 openssh 的最新漏洞"))
        self.assertTrue(_requires_tavily_search("search latest OpenSSH CVE"))
        self.assertFalse(_requires_tavily_search("解释一下ssh握手流程"))

    def test_forced_search_tool_call_is_emitted_to_timeline(self) -> None:
        message = _forced_tavily_tool_call("查询一下 openssh 的最新漏洞")
        rows = _raw_event_to_sse(
            {
                "event": "on_chain_end",
                "name": "search_gate",
                "data": {"output": {"messages": [message]}},
            }
        )
        tool_rows = [row for row in rows if row.get("event") == "tool"]
        self.assertTrue(tool_rows)
        self.assertEqual(tool_rows[0]["data"]["phase"], "planned")
        self.assertEqual(tool_rows[0]["data"]["tool"], "tavily_search")


if __name__ == "__main__":
    unittest.main()
