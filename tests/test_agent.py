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
from validator.review import CHECKS, education_requirements  # noqa: E402

ENTROPY = (ROOT / "template" / "fixtures" / "entropy.txt").read_text(encoding="utf-8")
FAKE_KEY = "test-not-a-real-key"
H = "-sum(p.map(xlog2x))"


def entropy_review(**changes) -> str:
    """A stub review of the entropy fixture: everything passes, one calculator entry per numeric claim."""
    review = {
        "summary": "Stub review.",
        "education": [{"heading": h, "status": "pass", "evidence": "stub"} for h in education_requirements()[1]],
        "checks": [{"name": c, "status": "pass", "evidence": "stub"} for c in CHECKS],
        "issues": [],
        "calculations": [
            {"id": "certain", "field": "explorations[0].observe", "quote": "drops to exactly 0 bits", "value": 0, "source": "Theorem 2", "formula": H},
            {"id": "uniform", "field": "explorations[1].observe", "quote": "{H} = 2 bits", "value": 2, "source": "Theorem 2", "formula": H},
            {"id": "share", "field": "explorations[1].observe", "quote": "exactly 0.5 bits", "value": 0.5, "source": "Theorem 2", "formula": "-xlog2x(p[0])"},
        ] + [{"id": f"test{i}", "field": f"tests[{i}].expect.H", "source": "Theorem 2", "formula": H} for i in range(4)],
    }
    review.update(changes)
    return json.dumps(review)


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
    def run_agent(self, replies: list, case: str | dict = "entropy", paper: bool = True):
        """replies: model contents in call order; a (content, tool_ran) tuple answers a server-tool call.
        case: a practice case name or a case dict; paper: add a converted paper.md for the validator's review."""
        queue = list(replies)

        def post(body, timeout):
            item = queue.pop(0)
            return fake_response(*item) if isinstance(item, tuple) and len(item) == 3 else \
                fake_response(item[0], 400, 300, item[1]) if isinstance(item, tuple) else fake_response(item)

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            data = dict(case) if isinstance(case, dict) else \
                json.loads((ROOT / "examples" / f"{case}.json").read_text(encoding="utf-8"))
            if paper:   # the converted paper the validator reviews against
                (Path(tmp) / "paper.md").write_text("# Section 6\n\nH = -K sum p_i log p_i (Theorem 2).\n", encoding="utf-8")
                data["paper_md"] = "paper.md"
            (Path(tmp) / "case.json").write_text(json.dumps(data), encoding="utf-8")
            argv = ["agent.py", "--input", str(Path(tmp) / "case.json"), "--output", str(out), "--model", "stub/model"]
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

    def test_valid_reply_needs_generation_and_one_review(self):
        code, trace, html, raw = self.run_agent([ENTROPY, entropy_review()])
        self.assertEqual(code, 0)
        self.assertEqual([c["stage"] for c in self.calls(trace)], ["generate", "review"])
        self.assertIn("Entropy: how much does an outcome surprise you", html)
        summary = trace[-1]
        self.assertEqual((summary["result"], summary["total_tokens"], summary["revisions"]), ("success", 11000, 0))
        self.assertEqual(sum(e["action"] == "calculator" and e["result"] == "pass" for e in trace), 7)
        self.assertNotIn(FAKE_KEY, raw)
        self.assertNotIn("paper.md", json.dumps(next(e for e in trace if e["stage"] == "generate")))

    def test_wrong_number_found_by_calculator_is_repaired(self):
        wrong = ENTROPY.replace("{H} = 2 bits, the gauge", "{H} = 3 bits, the gauge")
        review = json.loads(entropy_review())
        review["calculations"][1].update(quote="{H} = 3 bits", value=3)
        fixed = "<content>\n" + parse_reply(ENTROPY)["content"] + "\n</content>"
        code, trace, html, _ = self.run_agent([wrong, json.dumps(review), fixed, entropy_review()])
        self.assertEqual(code, 0)
        self.assertEqual([c["stage"] for c in self.calls(trace)], ["generate", "review", "revise", "review"])
        first = next(e for e in trace if e["action"] == "validate")
        self.assertEqual(len(first["failures"]), 1)
        self.assertIn("[calculator/math_check] explorations[1].observe", first["failures"][0])

    def test_reply_cut_off_before_render_gets_a_small_repair(self):
        parts = parse_reply(ENTROPY)
        cut = "\n".join(f"<{k}>\n{parts[k]}\n</{k}>" for k in ("content", "controls", "compute")) + "\n<render>\nfunction render(s, r, kit) {"
        rest = "\n".join(f"<{k}>\n{parts[k]}\n</{k}>" for k in ("render", "checks", "tests"))
        code, trace, html, _ = self.run_agent([cut, rest, entropy_review()])
        self.assertEqual(code, 0)
        repair = [e for e in trace if e["stage"] == "revise" and e["action"] == "model_call" and e["result"] == "started"][0]
        self.assertEqual(repair["max_tokens"], agent.FIX_TOKENS)
        first = next(e for e in trace if e["action"] == "validate")
        self.assertEqual(first["failures"], ["missing <render> block", "missing <tests> block"])

    def test_without_paper_md_the_review_uses_the_excerpt(self):
        # The assessment's case.json has no paper_md: the review reads the excerpt the generator wrote from.
        code, trace, html, _ = self.run_agent([ENTROPY, entropy_review()], paper=False)
        self.assertEqual(code, 0)
        self.assertEqual([c["stage"] for c in self.calls(trace)], ["generate", "review"])
        self.assertTrue(any(e["action"] == "load_paper" and e.get("source") == "excerpt" for e in trace))
        self.assertTrue(trace[-1]["reviewed"])

    def test_no_paper_text_at_all_ships_checked_page_without_review(self):
        # No paper_md, no excerpt and no URL to retrieve from: runtime checks still pass, so the run succeeds unreviewed.
        case = {"focus": "Explain discrete entropy in bits.", "audience": "Engineering undergraduate"}
        code, trace, html, _ = self.run_agent([ENTROPY], case=case, paper=False)
        self.assertEqual(code, 0)
        self.assertIsNotNone(html)
        self.assertEqual(len(self.calls(trace)), 1)
        self.assertEqual((trace[-1]["result"], trace[-1]["reviewed"]), ("success", False))

    def test_failed_check_repairs_only_the_failing_block(self):
        broken = ENTROPY.replace('"expect": {"H": 1}', '"expect": {"H": 1.5}')
        fix = "<tests>\n" + parse_reply(ENTROPY)["tests"] + "\n</tests>"
        code, trace, html, _ = self.run_agent([broken, fix, entropy_review()])
        self.assertEqual(code, 0)
        self.assertEqual(len(self.calls(trace)), 3)
        merge = next(e for e in trace if e["action"] == "merge_blocks")
        self.assertEqual(merge["replaced_blocks"], ["tests"])
        first_check = next(e for e in trace if e["action"] == "validate")
        self.assertTrue(any("expected H = 1.5" in f for f in first_check["failures"]))

    def test_unparseable_reply_is_asked_again(self):
        code, trace, html, _ = self.run_agent(["Sorry, here is a summary instead.", ENTROPY, entropy_review()])
        self.assertEqual(code, 0)
        self.assertEqual(len(self.calls(trace)), 3)
        regen = [e for e in trace if e["stage"] == "revise" and e["action"] == "model_call" and e["result"] == "started"][0]
        self.assertEqual((regen["reasoning"], regen["max_tokens"]), ("off", agent.REGEN_TOKENS))
        review = [e for e in trace if e["stage"] == "review" and e["action"] == "model_call" and e["result"] == "started"][0]
        self.assertEqual(review["reasoning"], "off")

    def test_reask_for_an_unusable_reply_does_not_use_up_a_repair(self):
        broken = ENTROPY.replace('"expect": {"H": 1}', '"expect": {"H": 1.5}')
        still = "<tests>\n" + parse_reply(broken)["tests"] + "\n</tests>"
        fix = "<tests>\n" + parse_reply(ENTROPY)["tests"] + "\n</tests>"
        code, trace, html, _ = self.run_agent(["Sorry, no blocks.", broken, still, fix, entropy_review()])
        self.assertEqual(code, 0)
        self.assertEqual([c["stage"] for c in self.calls(trace)], ["generate", "revise", "revise", "revise", "review"])
        self.assertEqual(trace[-1]["revisions"], agent.MAX_REPAIRS)

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
        code, trace, html, _ = self.run_agent([ENTROPY, entropy_review()])
        self.assertEqual(self.source_events(trace), [("decide", "supplied")])
        self.assertIn('"source_mode": "supplied"', html)

    def test_missing_excerpt_is_retrieved_by_search(self):
        code, trace, html, _ = self.run_agent([(extract(), 1), ATTENTION, entropy_review(calculations=[])], case=self.URL_ONLY, paper=False)
        self.assertEqual(code, 0)
        self.assertIn(("accept", "passed"), self.source_events(trace))
        accepted = next(e for e in trace if e["action"] == "accept")
        self.assertEqual(accepted["tool"], "openrouter:web_search")
        self.assertIn('"source_mode": "searched"', html)

    def test_wrong_paper_or_memory_falls_through_to_fetch(self):
        replies = [(extract("https://arxiv.org/abs/1810.04805"), 1),   # search returned a different paper
                   (extract(), 1), ATTENTION, entropy_review(calculations=[])]                   # fetch reads the right one
        code, trace, html, _ = self.run_agent(replies, case=self.URL_ONLY, paper=False)
        self.assertEqual(code, 0)
        rejected = next(e for e in trace if e["action"] == "reject")
        self.assertTrue(any("not the case's paper" in r for r in rejected["reasons"]))
        self.assertIn('"source_mode": "fetched"', html)
        replies = [(extract(), 0), (extract(), 1), ATTENTION, entropy_review(calculations=[])]   # tool never ran: recalled, not read
        code, trace, html, _ = self.run_agent(replies, case=self.URL_ONLY, paper=False)
        self.assertTrue(any("tool did not run" in r for e in trace if e["action"] == "reject" for r in e["reasons"]))

    def test_no_excerpt_anywhere_still_generates_and_says_so(self):
        code, trace, html, _ = self.run_agent([("NOT_FOUND", 1), ("NOT_FOUND", 1), ATTENTION], case=self.URL_ONLY, paper=False)
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
