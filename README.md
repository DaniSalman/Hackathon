# Paper to Playground

A reusable Python 3.11 agent that turns a focused research-paper excerpt and a learning brief into one
self-contained, interactive HTML explanation, paced one idea at a time in a style inspired by 3Blue1Brown.

**Team:** Dani Salman, Ibrahim, Samer *(full names to be completed)*

**MODEL_ID:** `deepseek/deepseek-v4.1-flash` (via OpenRouter)

## Run

```sh
python -m pip install -r requirements.txt
export OPENROUTER_API_KEY=...            # read from the environment; never stored or logged
python agent.py --input examples/entropy.json --output out --model deepseek/deepseek-v4.1-flash
```

Outputs: `out/index.html` (single offline file, opens in Chromium), `out/trace.jsonl` (one event per line),
`out/reply.txt` (the model's final tagged reply). Exit code 0 = page written and all checks pass,
2 = page written but some checks still fail after repairs, 1 = no usable page.

## Architecture

```
case.json ─▶ 1 generation call ─▶ validator/ ─────────────────────────▶ [repair call: failing blocks only] ─▶ fixed template ─▶ index.html
             system: teaching rules   1. runtime checks (no model)          ≤ 2, only if a check fails          template/ (HTML, CSS,
             + kit API + 1 example    2. review vs paper (1 call, ≤ 2/run)                                       JS kit) pasted in by Python
                                      3. calculator on every numeric claim
```

- **The model writes only paper-specific pieces**, as tagged blocks: `content` (text, symbols, scenes, explorations,
  grounding), `controls`, `compute(s)` (the formula), `render(s, r, kit)` (which panels show which numbers),
  `checks` (live invariants) and `tests` (numeric oracles).
- **Everything visual is pre-written and costs no tokens** (`template/`): layout, 3b1b-style theme, components
  (bars, matrix, plot, 2-D plane, graph, steps, readout, formula), draggable visuals bound to inputs, linked
  highlighting, eased motion, "Try it" explorations, live checks, and stage-by-stage reveal with "pause and ponder" questions.
- **The validator does every check** (`validator/`); the generator only generates. Failures are sent back verbatim and
  the model returns only the blocks it changes.
  1. *Runtime checks* (`validator/runtime.py`, no model): required blocks and fields, ≥ 2 controls, 2 explorations,
     grounding; `compute` runs in QuickJS on the defaults, every exploration preset and every test state (no throws, no NaN,
     oracles match, live checks hold); `render` runs against a mock kit (no crashes, finite data, no "undefined" text,
     valid scenes and bindings).
  2. *Review* (`validator/review.py`, one model call, only once no blocking runtime failure remains, at most 2 per run): the reply is
     judged against the full paper (`paper_md` in `case.json`, a Markdown file converted beforehand, relative to the case
     file) and `education_requirements.md`. The reviewer grades each education heading and writes one calculator entry per
     numeric claim, with the formula taken from the paper. It also sees the kit API, to judge claimed interactions. The
     review runs with reasoning off (with `minimal`, live reviews spent the whole cap reasoning over a full paper).
     It may not judge numbers: a finding that states a number found nowhere in the reply or paper (the reviewer did
     arithmetic) or disputes a number the calculator verified is withheld from the generator and logged. Live reviews
     did both (e.g. "the weight is ≈ 0.865" for a correct 0.998).
  3. *Calculator* (`validator/calculator.py`, no model): runs each formula in QuickJS on the page's real state (defaults
     plus the exploration preset or test state) and compares it with the number the reply states, to the precision it is
     written in (`≈ 0.998` allows ±0.0005). Only mismatches reach the generator, and only from formulas that read the
     page state (a reviewer typing `9/2` for `9/√2` must not blame the generator); passes and unusable reviewer entries
     go to the trace. After a repair with no review left, the stored entries are re-run for free and the earlier review is
     trusted.

  No `paper_md` (or an unreadable file) skips the review: the page ships with exit code 2.
- **Repairs only for visible problems:** a test oracle off by ≤ 5 % or a live check failing only in an extreme test state is
  logged as a warning; crashes, NaN, broken bindings or presets, empty scenes, larger disagreements and review or
  calculator findings trigger a repair.
- **Budgets** (per case): ≤ 8 requests including retries (limit 10), ≤ 29,000 reserved completion tokens (limit 30,000),
  560 s deadline (limit 600 s). Reasoning is off by default (`P2P_REASONING`). Measured on both practice cases: `low`
  reasoning cost 19–37k tokens and 80–225 s per case (once its hidden reasoning exhausted the output cap and returned
  nothing), while `off` cost 9–17k tokens and 24–41 s with equally correct pages; on the attention case `minimal` spent
  12.6k/12.5k of a 14k cap reasoning with no usable reply. The validator catches what the faster reply gets wrong. Fastest
  provider first (`P2P_PROVIDER_SORT=throughput`; one provider took 217 s for a call another serves in 34 s). A reply cut
  off after `compute` gets a small repair for the missing blocks; a reply with nothing usable is re-asked once, without
  reasoning, and that re-ask does not use up one of the 2 repairs. The source URL is cited, never fetched.
- **Trace:** every model call logs prompt / completion / reasoning tokens, OpenRouter generation id, finish reason and seconds;
  every validation logs the checks that passed and the failures; repairs log which blocks were replaced. No credentials,
  no hidden reasoning.

## Example input / output (real run)

Generated by `deepseek/deepseek-v4.1-flash` with the committed code (`index.html`, `trace.jsonl`, `reply.txt` in each folder):

| Input | Output | Calls | Tokens | Time |
|---|---|---|---|---|
| `examples/entropy.json` | `examples/showcase/entropy/` | 1 (all checks passed first time) | 8,916 | 37 s |
| `examples/attention.json` | `examples/showcase/attention/` | 2 (first reply had NaN in the output row; one repair) | 16,918 | 29 s |

Assessed outputs are generated afresh.

## Tests

```sh
python -m unittest discover -s tests -v                     # offline; the model is stubbed
python -m validator.runtime template/fixtures/entropy.txt   # runtime checks for one reply
python -m validator --input case.json --reply reply.txt --output check-out --model MODEL_ID   # full validation
```

## Repository

| Path | Purpose |
|---|---|
| `agent.py` | CLI, OpenRouter client with budgets, generate → validator → repair loop, trace |
| `validator/` | every check: runtime checks, review against the paper, calculator; `education_requirements.md` is its rubric |
| `template/` | page template, kit, math helpers, prompt, assembler (see `template/README.md`) |
| `template/fixtures/` | hand-written replies for the two public practice cases: the one-shot format example in the prompt and test data |
| `examples/` | practice inputs (paraphrased excerpts) and the showcase output |
| `tests/` | offline tests of the agent loop |

## Credits

- [QuickJS](https://bellard.org/quickjs/) via the `quickjs` Python binding (MIT) runs generated JavaScript for checks.
- Visual style inspired by 3Blue1Brown and the Manim colour palette; no code, fonts or assets were copied. All page code
  (HTML, CSS, `kit.js`, `mathlib.js`) was written for this project with AI coding assistants (Claude Code, Codex).
- OpenRouter chat-completions API. Practice sources: Shannon, *A Mathematical Theory of Communication*, Section 6;
  Vaswani et al., *Attention Is All You Need*, Section 3.2.1.
