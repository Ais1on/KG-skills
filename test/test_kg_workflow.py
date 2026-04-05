from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kg_agent.services.stream import _raw_event_to_sse

from kg_agent.kg_workflow import (
    coerce_extraction_result,
    detect_workflow_mode,
    extract_python_code,
    normalize_graph_payload,
    summarize_graph_payload,
)


class KgWorkflowTests(unittest.TestCase):
    def test_detects_text_extraction_requests(self) -> None:
        self.assertEqual(
            detect_workflow_mode("请从下面文本中提取实体关系三元组：张三在OpenAI工作。"),
            "text_extraction_skill",
        )
        self.assertEqual(
            detect_workflow_mode("帮我执行这段Python代码并返回结果```python\nprint('ok')\n```"),
            "code_sandbox",
        )
        self.assertEqual(detect_workflow_mode("解释一下 SSH 握手流程"), "assistant")

    def test_extracts_python_code_from_fenced_block(self) -> None:
        code = extract_python_code("请执行\n```python\nprint('hello')\n```\n并告诉我结果")
        self.assertEqual(code, "print('hello')")

    def test_normalizes_entities_and_triplets(self) -> None:
        payload = normalize_graph_payload(
            {
                "entities": [
                    {"name": "OpenSSH", "type": "software"},
                    {"name": "openssh", "type": "project"},
                    "CVE-2024-6387",
                ],
                "triplets": [
                    {"head": "OpenSSH", "relation": "affected_by", "tail": "CVE-2024-6387"},
                    {"head": "openssh", "relation": "affected_by", "tail": "cve-2024-6387"},
                ],
            }
        )
        self.assertEqual(len(payload["entities"]), 2)
        self.assertEqual(payload["entities"][0]["name"], "OpenSSH")
        self.assertEqual(payload["entities"][1]["name"], "CVE-2024-6387")
        self.assertEqual(len(payload["triplets"]), 1)
        self.assertEqual(payload["triplets"][0]["tail"], "CVE-2024-6387")

    def test_coerces_structured_extraction_result(self) -> None:
        payload = coerce_extraction_result(
            {
                "entities": [
                    {"name": "OpenSSH", "type": "software", "properties": {"vendor": "OpenBSD"}},
                    {"name": "openssh", "type": "project"},
                ],
                "triplets": [
                    {
                        "head": "OpenSSH",
                        "relation": "affected_by",
                        "tail": "CVE-2024-6387",
                        "properties": {"severity": "high"},
                    }
                ],
                "sandbox_code": "print('ok')",
            }
        )
        self.assertEqual(payload["entities"][0]["name"], "OpenSSH")
        self.assertEqual(payload["entities"][0]["properties"]["vendor"], "OpenBSD")
        self.assertEqual(payload["triplets"][0]["properties"]["severity"], "high")
        self.assertEqual(payload["sandbox_code"], "print('ok')")

    def test_summarizes_graph_payload(self) -> None:
        text = summarize_graph_payload(
            {
                "entities": [{"name": "OpenSSH"}, {"name": "CVE-2024-6387"}],
                "triplets": [{"head": "OpenSSH", "relation": "affected_by", "tail": "CVE-2024-6387"}],
                "sandbox_result": "",
            }
        )
        self.assertIn("实体", text)
        self.assertIn("OpenSSH", text)
        self.assertIn("affected_by", text)

    def test_validator_events_emit_graph_data(self) -> None:
        rows = _raw_event_to_sse(
            {
                "event": "on_chain_end",
                "name": "validator",
                "data": {
                    "output": {
                        "entities": [{"name": "OpenSSH"}],
                        "triplets": [{"head": "OpenSSH", "relation": "affected_by", "tail": "CVE-2024-6387"}],
                    }
                },
            }
        )
        event_names = [row["event"] for row in rows]
        self.assertIn("graph_data", event_names)
        self.assertIn("orchestration", event_names)


if __name__ == "__main__":
    unittest.main()
