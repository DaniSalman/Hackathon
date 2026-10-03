"""Offline tests for agent.py: the model is stubbed, the checks really run (QuickJS, or Node locally).

    python -m unittest discover -s tests -v
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import agent  # noqa: E402
from template.assemble import build_page, parse_reply  # noqa: E402

ENTROPY = (ROOT / "template" / "fixtures" / "entropy.txt").read_text(encoding="utf-8")
FAKE_KEY = "test-not-a-real-key"


def fake_response(content: str, pt: int = 3000, ct: int = 2500) -> dict:
    return {"id": "gen-test", "model": "stub/model", "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": pt, "completion_tokens": ct, "completion_tokens_details": {"reasoning_tokens": 0}}}


class AgentTests(unittest.TestCase):
    def run_agent(self, replies: list[str], case: str = "entropy"):
        queue = list(replies)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            argv = ["agent.py", "--input", str(ROOT / "examples" / f"{case}.json"), "--output", str(out), "--model", "stub/model"]
            with patch.dict(os.environ, {"OPENROUTER_API_KEY": FAKE_KEY}), patch.object(sys, "argv", argv), \
                    patch.object(agent.Client, "_post", side_effect=lambda body, timeout: fake_response(queue.pop(0))):
                code = agent.main()
            raw_trace = (out / "trace.jsonl").read_text(encoding="utf-8")
            trace = [json.loads(line) for line in raw_trace.splitlines()]
            html = (out / "index.html").read_text(encoding="utf-8") if (out / "index.html").exists() else None
        return code, trace, html, raw_trace

    @staticmethod
    def calls(trace):
        return [e for e in trace if e["action"] == "model_call" and e["result"] == "completed"]

    def test_valid_reply_needs_one_call(self):
        code, trace, html, raw = self.run_agent([ENTROPY])
        self.assertEqual(code, 0)
        self.assertEqual(len(self.calls(trace)), 1)
        self.assertIn("Entropy: how much does an outcome surprise you", html)
        summary = trace[-1]
        self.assertEqual((summary["result"], summary["total_tokens"], summary["revisions"]), ("success", 5500, 0))
        self.assertNotIn(FAKE_KEY, raw)

    def test_failed_check_repairs_only_the_failing_block(self):
        broken = ENTROPY.replace('"expect": {"H": 1}', '"expect": {"H": 1.5}')
        fix = "<tests>\n" + parse_reply(ENTROPY)["tests"] + "\n</tests>"
        code, trace, html, _ = self.run_agent([broken, fix])
        self.assertEqual(code, 0)
        self.assertEqual(len(self.calls(trace)), 2)
        merge = next(e for e in trace if e["action"] == "merge_blocks")
        self.assertEqual(merge["replaced_blocks"], ["tests"])
        first_check = next(e for e in trace if e["action"] == "validate")
        self.assertTrue(any("expected H = 1.5" in f for f in first_check["failures"]))

    def test_unparseable_reply_is_asked_again(self):
        code, trace, html, _ = self.run_agent(["Sorry, here is a summary instead.", ENTROPY])
        self.assertEqual(code, 0)
        self.assertEqual(len(self.calls(trace)), 2)

    def test_unfixable_reply_still_ships_best_page(self):
        broken = ENTROPY.replace('"expect": {"H": 1}', '"expect": {"H": 1.5}')
        still = "<tests>\n" + parse_reply(broken)["tests"] + "\n</tests>"
        code, trace, html, _ = self.run_agent([broken, still, still])
        self.assertEqual(code, 2)
        self.assertIsNotNone(html)
        self.assertEqual(trace[-1]["result"], "partial")
        self.assertLessEqual(len(self.calls(trace)), 1 + agent.MAX_REPAIRS)

    def test_budget_blocks_before_network(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"OPENROUTER_API_KEY": FAKE_KEY}):
            client = agent.Client("stub/model", agent.Trace(Path(tmp) / "trace.jsonl"))
            client.calls = agent.MAX_CALLS
            with patch.object(agent.Client, "_post") as post, self.assertRaises(RuntimeError):
                client.chat("test", [{"role": "user", "content": "hi"}], 100)
            post.assert_not_called()

    def test_script_payload_is_escaped(self):
        parts = parse_reply(ENTROPY)
        content = json.loads(parts["content"])
        content["title"] = "</script><script>alert(1)</script>"
        parts["content"] = json.dumps(content)
        html = build_page(parts, {"source_url": "https://example.org"})
        self.assertNotIn("</script><script>alert(1)", html)


if __name__ == "__main__":
    unittest.main()
