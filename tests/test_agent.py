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


def fake_response(content: str, pt: int = 3000, ct: int = 2500) -> dict:
    return {"id": "gen-test", "model": "stub/model", "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": pt, "completion_tokens": ct, "completion_tokens_details": {"reasoning_tokens": 0}}}


class AgentTests(unittest.TestCase):
    def run_agent(self, replies: list[str], case: str = "entropy", paper: bool = True):
        queue = list(replies)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            data = json.loads((ROOT / "examples" / f"{case}.json").read_text(encoding="utf-8"))
            if paper:   # the converted paper the validator reviews against
                (Path(tmp) / "paper.md").write_text("# Section 6\n\nH = -K sum p_i log p_i (Theorem 2).\n", encoding="utf-8")
                data["paper_md"] = "paper.md"
            (Path(tmp) / "case.json").write_text(json.dumps(data), encoding="utf-8")
            argv = ["agent.py", "--input", str(Path(tmp) / "case.json"), "--output", str(out), "--model", "stub/model"]
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

    def test_missing_paper_ships_page_without_review(self):
        code, trace, html, _ = self.run_agent([ENTROPY], paper=False)
        self.assertEqual(code, 2)
        self.assertIsNotNone(html)
        self.assertEqual(len(self.calls(trace)), 1)
        self.assertEqual(trace[-1]["result"], "partial")

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

    def test_script_payload_is_escaped(self):
        parts = parse_reply(ENTROPY)
        content = json.loads(parts["content"])
        content["title"] = "</script><script>alert(1)</script>"
        parts["content"] = json.dumps(content)
        html = build_page(parts, {"source_url": "https://example.org"})
        self.assertNotIn("</script><script>alert(1)", html)


if __name__ == "__main__":
    unittest.main()
