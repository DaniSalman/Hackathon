#!/usr/bin/env python3
"""Paper to Playground: one generation call -> validator -> targeted repair -> fixed template.

    python agent.py --input case.json --output out --model deepseek/deepseek-v4.1-flash

The model returns tagged blocks (content, controls, compute, render, checks, tests). The validator
(validator/) does every check: runtime checks without a model (structure, QuickJS execution of
compute/render/tests), then a review against the paper named by case.json's paper_md with calculator
checks of every numeric claim. The same model fixes only the failing blocks when needed, and the result
is pasted into the pre-written template in template/. Outputs: out/index.html (single offline file),
out/trace.jsonl, out/reply.txt.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from template.assemble import build_page, parse_reply
from template.prompting import system_prompt, user_prompt
from validator import Validator

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
START = time.monotonic()
MAX_SECONDS = 560            # hard limit is 600 s per case; keep a margin to write the page
MAX_CALLS = 8                # hard limit is 10 requests per case, retries included (generate, re-ask, 2 repairs, 2 reviews, 2 retries)
MAX_COMPLETION = 29000       # hard limit is 30,000 completion tokens per case
GEN_TOKENS = 14000           # cap for the generation call (reasoning tokens count inside this)
FIX_TOKENS = 7000            # cap for each repair call
REGEN_TOKENS = 10000         # cap for re-asking the whole reply, with reasoning off
MAX_REPAIRS = 2
EXCERPT_CHARS = 24000        # the excerpt is meant to be focused; cap prompt tokens
# off | minimal | low | medium | high. Measured live on deepseek-v4.1-flash, attention case: "low" spent 9.8k and
# "minimal" 12.6k and 12.5k of a 14k cap reasoning, each time with no usable reply; with reasoning off the same prompt
# returned a complete reply in 12 s (4.7k tokens) and the validator caught its mistakes. The entropy case worked at
# "minimal" (2.8k reasoning). Override with P2P_REASONING.
REASONING = os.environ.get("P2P_REASONING", "off")
PROVIDER_SORT = os.environ.get("P2P_PROVIDER_SORT", "throughput")   # OpenRouter provider routing; "" = default
EXCERPT_KEYS = ("excerpt", "source_excerpt", "paper_excerpt", "source_text", "text", "section_text")


def elapsed() -> float:
    return time.monotonic() - START


class Trace:
    """One JSON object per event: stage, action, result (+ details). Never credentials or reasoning."""

    def __init__(self, path: Path):
        self.path = path
        path.write_text("", encoding="utf-8")

    def log(self, stage: str, action: str, result: str, **extra):
        event = {"stage": stage, "action": action, "result": result, "elapsed_seconds": round(elapsed(), 3), **extra}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")


class Client:
    """OpenRouter chat client with request, completion-token and time budgets."""

    def __init__(self, model: str, trace: Trace):
        self.model, self.trace = model, trace
        self.calls = self.prompt_tokens = self.completion_tokens = self.reserved = 0
        self.key = os.environ.get("OPENROUTER_API_KEY")
        if not self.key:
            raise ValueError("Set OPENROUTER_API_KEY in the environment; no credential is embedded or logged.")

    def _post(self, body: bytes, timeout: float) -> dict:
        req = urllib.request.Request(ENDPOINT, data=body, method="POST", headers={
            "Content-Type": "application/json", "Authorization": "Bearer " + self.key,
            "X-Title": "Paper to Playground"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.load(response)

    def chat(self, stage: str, messages: list[dict], cap: int, reasoning: str | None = None,
             json_mode: bool = False) -> tuple[str, str]:
        """Return (content, finish_reason). Retries once on transport errors, within the budgets.

        reasoning overrides REASONING for this call; json_mode asks for a single JSON object (the review)."""
        reasoning = reasoning or REASONING
        for attempt in (1, 2):
            remaining = MAX_SECONDS - elapsed()
            if self.calls >= MAX_CALLS or remaining < 25 or self.reserved + cap > MAX_COMPLETION:
                raise RuntimeError("request, time or completion-token budget exhausted")
            self.calls += 1
            self.reserved += cap  # reserve the cap until real usage is known
            payload = {"model": self.model, "max_tokens": cap, "messages": messages, "usage": {"include": True}}
            if reasoning != "default":
                payload["reasoning"] = {"enabled": False} if reasoning == "off" else {"effort": reasoning, "exclude": True}
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            if PROVIDER_SORT:   # the same model is served by fast and very slow providers (34 s vs 217 s for one call)
                payload["provider"] = {"sort": PROVIDER_SORT}
            self.trace.log(stage, "model_call", "started", call=self.calls, attempt=attempt, max_tokens=cap, model=self.model,
                           reasoning=reasoning, prompt_characters=sum(len(m["content"]) for m in messages))
            t0 = time.monotonic()
            try:
                data = self._post(json.dumps(payload).encode(), timeout=max(10.0, min(300.0, remaining - 15)))
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                code = getattr(exc, "code", None)
                self.trace.log(stage, "model_call", "failed", call=self.calls, error_type=type(exc).__name__, http_status=code,
                               seconds=round(time.monotonic() - t0, 2), usage_verifiable=False)
                if attempt == 1 and (code is None or code == 429 or code >= 500) and MAX_SECONDS - elapsed() > 60:
                    time.sleep(2)
                    continue
                raise RuntimeError("OpenRouter request failed (see trace; credentials omitted)") from None
            usage = data.get("usage") or {}
            pt, ct = usage.get("prompt_tokens"), usage.get("completion_tokens")
            if not isinstance(pt, int) or not isinstance(ct, int):
                self.trace.log(stage, "model_call", "failed", call=self.calls, error="response lacks token usage", usage_verifiable=False)
                raise RuntimeError("OpenRouter response lacks verifiable token usage")
            self.reserved += ct - cap
            self.prompt_tokens += pt
            self.completion_tokens += ct
            choice = (data.get("choices") or [{}])[0]
            content = (choice.get("message") or {}).get("content") or ""
            finish = choice.get("finish_reason") or choice.get("native_finish_reason") or ""
            self.trace.log(stage, "model_call", "completed", call=self.calls, generation_id=data.get("id"), model_used=data.get("model"),
                           provider=data.get("provider"), prompt_tokens=pt, completion_tokens=ct, total_tokens=pt + ct,
                           reasoning_tokens=(usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
                           cached_prompt_tokens=(usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
                           cost=usage.get("cost"), finish_reason=finish, reply_characters=len(content),
                           seconds=round(time.monotonic() - t0, 2), usage_verifiable=True)
            return content, finish
        raise RuntimeError("unreachable")


def load_case(path: Path, trace: Trace) -> dict:
    """Accept any string fields; the excerpt may arrive under several names. Never fetch the URL."""
    case = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(case, dict) or not any(isinstance(v, str) and v.strip() for v in case.values()):
        raise ValueError("case.json must be a JSON object with string fields")
    missing = [k for k in ("source_url", "focus", "audience") if not (isinstance(case.get(k), str) and case[k].strip())]
    excerpt_key = next((k for k in EXCERPT_KEYS if isinstance(case.get(k), str) and case[k].strip()), None)
    if excerpt_key and len(case[excerpt_key]) > EXCERPT_CHARS:
        case = {**case, excerpt_key: case[excerpt_key][:EXCERPT_CHARS] + " [...]"}
    trace.log("input", "load_case", "passed" if not missing else "warning", fields=sorted(case), missing_fields=missing,
              excerpt_field=excerpt_key, excerpt_characters=len(case[excerpt_key]) if excerpt_key else 0,
              note="source_url is cited, never fetched (assessment network allows OpenRouter only)")
    return case


def blocking(report: dict) -> list[str]:
    """Failures that change what the learner or grader sees. Minor ones (an oracle off by <= 5 %,
    a live check failing only in an extreme test state) are logged as warnings, not repaired."""
    minor = set(report.get("minor", []))
    return [f for f in report["failures"] if f not in minor]


def score(report: dict) -> int:
    """Lower is better: hard failures (missing blocks, crashes, bad JSON) dominate, then failing to run at all,
    then blocking ones."""
    hard = sum(1 for f in report["failures"] if any(s in f for s in ("missing <", "invalid JSON", "could not run", "compute threw", "render threw")))
    runs = report.get("stage") in ("review", "recheck") or not blocking(report)   # passed the validator's runtime stage
    return hard * 1000 + (0 if runs else 500) + len(blocking(report)) * 10 + len(report["failures"])


def as_reply(parts: dict) -> str:
    return "\n".join(f"<{k}>\n{v}\n</{k}>" for k, v in parts.items())


def repair_messages(case: dict, parts: dict, failures: list[str]) -> list[dict]:
    """Lean repair prompt: rules + API (no example), the previous reply and the concrete failures."""
    ask = ("\n\nYour previous reply:\n" + as_reply(parts) +
           "\n\nAutomatic checks found these problems:\n- " + "\n- ".join(failures[:25]) +
           "\n\nFor each problem decide whether compute, the live check or the test is wrong, and make all three agree; "
           "keep everything that already works. Return ONLY the blocks that need changes, each complete and in the same tags; "
           "omitted blocks are kept as they are.")
    return [{"role": "system", "content": system_prompt(example=None)},
            {"role": "user", "content": user_prompt(case) + ask}]


def _deadline(*_):
    raise TimeoutError("hard execution deadline reached")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    trace = Trace(args.output / "trace.jsonl")
    if hasattr(signal, "SIGALRM"):
        signal.signal(signal.SIGALRM, _deadline)
        signal.alarm(MAX_SECONDS + 15)

    case, client, best, best_report, revisions, regenerated = None, None, None, None, 0, False
    try:
        case = load_case(args.input, trace)
        client = Client(args.model, trace)
        validator = Validator(case, args.input, client, trace, budget=lambda: {
            "tokens": MAX_COMPLETION - client.reserved, "seconds": MAX_SECONDS - elapsed(), "calls": MAX_CALLS - client.calls})
        case = {k: v for k, v in case.items() if k != "paper_md"}   # the generator never sees the paper path
        reply, finish = client.chat("generate", [{"role": "system", "content": system_prompt()},
                                                 {"role": "user", "content": user_prompt(case)}], GEN_TOKENS)
        parts = parse_reply(reply)
        trace.log("generate", "parse_reply", "passed" if parts else "failed", blocks=sorted(parts), truncated=finish == "length")
        while True:
            report = validator.check(as_reply(parts))
            must_fix = blocking(report)
            trace.log("check", "validate", "passed" if report["ok"] else "warnings" if not must_fix else "failed", revision=revisions,
                      validator_stage=report["stage"], complete=report["complete"], checks_passed=report["passed"],
                      failures=must_fix, warnings=report.get("minor", []), validator_errors=report["validator_errors"])
            if best_report is None or score(report) < score(best_report):
                best, best_report = dict(parts), report
            usable = all(k in best for k in ("content", "controls", "compute"))
            if not must_fix or (usable and revisions >= MAX_REPAIRS) or (not usable and regenerated):
                break
            if MAX_SECONDS - elapsed() < 120 or MAX_COMPLETION - client.reserved < 3000 or client.calls >= MAX_CALLS:
                trace.log("revise", "repair", "skipped", reason="not enough time or budget left for another call")
                break
            if usable:
                # includes a reply cut off at the token cap: ask only for the missing blocks, not a new generation
                revisions += 1
                messages, cap = repair_messages(case, best, best_report["failures"]), FIX_TOKENS
            else:  # nothing usable came back: ask once more for the whole reply; this does not use up a repair
                regenerated = True
                messages = [{"role": "system", "content": system_prompt()},
                            {"role": "user", "content": user_prompt(case) + "\n\nYour previous reply could not be parsed. "
                             "Reply again with all six tagged blocks."}]
                cap = REGEN_TOKENS
            # A whole-reply re-ask runs without reasoning, so reasoning cannot swallow it again (seen live at "minimal").
            fix, finish = client.chat("revise", messages, min(cap, MAX_COMPLETION - client.reserved),
                                      reasoning=None if usable else "off")
            new = parse_reply(fix)
            trace.log("revise", "merge_blocks", "passed" if new else "failed", revision=revisions, replaced_blocks=sorted(new),
                      truncated=finish == "length")
            parts = {**best, **new}
    except Exception as exc:  # budgets, network, deadline, bad input: still ship the best page we have
        trace.log("finish", "abort", "failed", error_type=type(exc).__name__, error=str(exc)[:300])
    finally:
        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)

    usable = best is not None and "content" in best and "compute" in best and "render" in best
    if usable:
        page = build_page(best, case)
        (args.output / "index.html").write_text(page, encoding="utf-8")
        (args.output / "reply.txt").write_text(as_reply(best), encoding="utf-8")
        trace.log("output", "write_page", "passed", file="index.html", bytes=len(page.encode("utf-8")),
                  remaining_failures=blocking(best_report), remaining_warnings=best_report.get("minor", []))
    status = "success" if usable and not blocking(best_report) and best_report["complete"] else "partial" if usable else "failed"
    trace.log("finish", "summary", status, calls=client.calls if client else 0, revisions=revisions,
              prompt_tokens=client.prompt_tokens if client else 0, completion_tokens=client.completion_tokens if client else 0,
              total_tokens=(client.prompt_tokens + client.completion_tokens) if client else 0, total_seconds=round(elapsed(), 2))
    if usable:
        print(str((args.output / "index.html").resolve()))
    else:
        print("Generation failed: no usable page (see trace.jsonl)", file=sys.stderr)
    return 0 if status == "success" else 2 if status == "partial" else 1


if __name__ == "__main__":
    sys.exit(main())
