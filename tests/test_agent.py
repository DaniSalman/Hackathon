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


ATTENTION = (ROOT / "template" / "fixtures" / "attention.txt").read_text(encoding="utf-8")
PAPER_URL = "https://arxiv.org/html/1706.03762v7"
PASSAGE = "We call our particular attention Scaled Dot-Product Attention. " * 12


def fake_response(content: str, pt: int = 3000, ct: int = 2500, tool_ran: int | None = None) -> dict:
    usage = {"prompt_tokens": pt, "completion_tokens": ct, "completion_tokens_details": {"reasoning_tokens": 0}}
    if tool_ran is not None:
        usage["server_tool_use_details"] = {"tool_calls_requested": 1, "tool_calls_executed": tool_ran}
    return {"id": "gen-test", "model": "stub/model", "choices": [{"message": {"content": content}, "finish_reason": "stop"}], "usage": usage}


def extract(source: str = PAPER_URL) -> str:
    return f"I'll search.SOURCE: {source}\nSECTION: 3.2.1 Scaled Dot-Product Attention\n\n{PASSAGE}"


class AgentTests(unittest.TestCase):
    def run_agent(self, replies: list, case: str | dict = "entropy"):
        """replies: model contents in call order; a (content, tool_ran) tuple answers a server-tool call."""
        queue = list(replies)

        def post(body, timeout):
            item = queue.pop(0)
            return fake_response(*item) if isinstance(item, tuple) and len(item) == 3 else \
                fake_response(item[0], 400, 300, item[1]) if isinstance(item, tuple) else fake_response(item)

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            if isinstance(case, dict):
                path = Path(tmp) / "case.json"
                path.write_text(json.dumps(case), encoding="utf-8")
            else:
                path = ROOT / "examples" / f"{case}.json"
            argv = ["agent.py", "--input", str(path), "--output", str(out), "--model", "stub/model"]
            with patch.dict(os.environ, {"OPENROUTER_API_KEY": FAKE_KEY}), patch.object(sys, "argv", argv), \
                    patch.object(agent.Client, "_post", side_effect=post):
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

    # ---- excerpt retrieval tiers ---------------------------------------------------------------
    URL_ONLY = {"source_url": PAPER_URL, "focus": "Explain scaled dot-product attention (Section 3.2.1).",
                "audience": "Engineering undergraduate"}

    def source_events(self, trace):
        return [(e["action"], e["result"]) for e in trace if e["stage"] == "source"]

    def test_supplied_excerpt_costs_no_retrieval(self):
        code, trace, html, _ = self.run_agent([ENTROPY])
        self.assertEqual(self.source_events(trace), [("decide", "supplied")])
        self.assertIn('"source_mode": "supplied"', html)

    def test_missing_excerpt_is_retrieved_by_search(self):
        code, trace, html, _ = self.run_agent([(extract(), 1), ATTENTION], case=self.URL_ONLY)
        self.assertEqual(code, 0)
        self.assertIn(("accept", "passed"), self.source_events(trace))
        accepted = next(e for e in trace if e["action"] == "accept")
        self.assertEqual(accepted["tool"], "openrouter:web_search")
        self.assertIn('"source_mode": "searched"', html)

    def test_wrong_paper_or_memory_falls_through_to_fetch(self):
        replies = [(extract("https://arxiv.org/abs/1810.04805"), 1),   # search returned a different paper
                   (extract(), 1), ATTENTION]                          # fetch reads the right one
        code, trace, html, _ = self.run_agent(replies, case=self.URL_ONLY)
        self.assertEqual(code, 0)
        rejected = next(e for e in trace if e["action"] == "reject")
        self.assertTrue(any("not the case's paper" in r for r in rejected["reasons"]))
        self.assertIn('"source_mode": "fetched"', html)
        replies = [(extract(), 0), (extract(), 1), ATTENTION]           # tool never ran: recalled, not read
        code, trace, html, _ = self.run_agent(replies, case=self.URL_ONLY)
        self.assertTrue(any("tool did not run" in r for e in trace if e["action"] == "reject" for r in e["reasons"]))

    def test_no_excerpt_anywhere_still_generates_and_says_so(self):
        code, trace, html, _ = self.run_agent([("NOT_FOUND", 1), ("NOT_FOUND", 1), ATTENTION], case=self.URL_ONLY)
        self.assertEqual(code, 0)
        self.assertIn('"source_mode": "none"', html)
        calls = [e for e in trace if e["action"] == "model_call" and e["result"] == "completed"]
        self.assertEqual(len(calls), 3)

    def test_script_payload_is_escaped(self):
        parts = parse_reply(ENTROPY)
        content = json.loads(parts["content"])
        content["title"] = "</script><script>alert(1)</script>"
        parts["content"] = json.dumps(content)
        html = build_page(parts, {"source_url": "https://example.org"})
        self.assertNotIn("</script><script>alert(1)", html)


if __name__ == "__main__":
    unittest.main()
