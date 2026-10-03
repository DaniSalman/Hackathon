# Paper to Playground

A reusable Python 3.11 agent that turns a focused research-paper excerpt and a learning brief into one
self-contained, interactive HTML explanation, paced one idea at a time in a style inspired by 3Blue1Brown.

**Team:** Dani Salman (page template, visual kit, prompt, agent loop), Ibrahim Khaled (validator: review and calculator), Samer Barakat (documentation, paper conversion)

**MODEL_ID:** `deepseek/deepseek-v4.1-flash` (via OpenRouter)

## Run

```sh
python -m pip install -r requirements.txt
export OPENROUTER_API_KEY=...            # read from the environment; never stored or logged
python agent.py --input examples/entropy.json --output out --model deepseek/deepseek-v4.1-flash
```

Outputs: `out/index.html` (single offline file, opens in Chromium), `out/trace.jsonl` (one event per line),
`out/reply.txt` (the model's final tagged reply), `out/excerpt.txt` (only when the excerpt had to be retrieved).
Exit code 0 = page written, no blocking failure, and its code was executed by the checks (whether the review ran is
recorded in the trace as `reviewed`); 2 = page written but blocking failures remain, or no JavaScript engine was
available to execute it; 1 = no usable page.

## Architecture

```
case.json ─▶ [excerpt retrieval, only if missing] ─▶ 1 generation call ─▶ validator ─▶ [repair: failing blocks only, ≤ 2] ─▶ fixed template ─▶ index.html
                                                                              │
                     stage 1  runtime checks  (no model, every reply) ────────┤ blocking failure → repair, no review spent
                     stage 2  review          (1 model call, ≤ 2 per run) ────┤ against paper_md if given, else the excerpt
                     stage 3  calculator      (no model) ─────────────────────┘ evaluates the review's formulas
```

- **The model writes only paper-specific pieces**, as tagged blocks: `content` (text, symbols, scenes, explorations,
  grounding), `controls`, `compute(s)` (the formula), `render(s, r, kit)` (which panels show which numbers),
  `checks` (live invariants) and `tests` (numeric oracles).
- **Everything visual is pre-written and costs no tokens** (`template/`): layout, 3b1b-style theme, components
  (bars, matrix, plot, 2-D plane, graph, steps, readout, formula), draggable visuals bound to inputs, linked
  highlighting, eased motion, "Try it" explorations, live checks, and stage-by-stage reveal with "pause and ponder" questions.
- **Validator** (`validator/`):
  - *Stage 1, runtime checks* (`validator/runtime.py`, no model): required blocks and fields, ≥ 2 controls, every control read
    by the code, 2 explorations, grounding; `compute` runs in QuickJS on the defaults, every exploration preset and every
    test state (no throws, no NaN, oracles match, live checks hold); `render` runs against a mock kit (no crashes, no NaN,
    no "undefined" text, valid scenes and bindings). A failure of the checker itself never triggers a repair.
  - *Stage 2, review* (`validator/review.py`, one model call, at most two per run, JSON mode, reasoning off): grades the reply
    against the paper text and `education_requirements.md`, and writes one formula per numeric claim. The paper text is the
    case's `paper_md` file when one is given (practice cases), otherwise the excerpt the generator wrote from, as in the
    assessment. A reply that fails stage 1 is never sent to review.
  - *Stage 3, calculator* (`validator/calculator.py`, no model): evaluates the review's formulas over the page's control
    values and compares them with the reply's numbers; the review never judges numbers itself.
  - Failures are sent back verbatim and the model returns only the blocks it changes.
- **Source excerpt.** A supplied excerpt (≥ 300 characters) is used as is, at no cost. Otherwise OpenRouter retrieves it
  server-side (this machine still talks only to OpenRouter): (a) `openrouter:web_search` restricted to the paper's site
  (all arXiv mirrors for arXiv ids), query-focused, measured 3.5–6.6k tokens; (b) `openrouter:web_fetch` of the HTML page with
  a 6,000-token reading cap; (c) otherwise generation proceeds from the brief and the page says no excerpt was available.
  A retrieved passage is accepted only if the model names the page it read, that page is the same paper (arXiv id, or host
  and path), the tool actually ran, and the passage has ≥ 60 words; it is saved to `out/excerpt.txt`.
- **Provider routing:** `provider.sort = "throughput"` keeps the supplied model but prefers its fastest hosts
  (measured 25–290 tokens/s across hosts of the same model).
- **Budgets** (per case): ≤ 10 requests including retries (the limit; worst case: 2 retrievals, generate, re-ask, 2 repairs,
  2 reviews, 2 retries), ≤ 29,000 reserved completion tokens (limit 30,000), 560 s deadline (limit 600 s). Each call is
  refused before it is sent if it could break a limit.
- **Reasoning is disabled** (`P2P_REASONING=off`, the default). Measured on both practice cases: `low` reasoning cost
  19–37k tokens and 80–225 s per case (once its hidden reasoning exhausted the output cap and returned nothing), while `off`
  cost 9–17k tokens and 24–41 s with equally correct pages; the validator and repair loop catch what reasoning would have.
- **Repairs only for visible problems:** a test oracle off by ≤ 5 % or a live check failing only in an extreme test state is
  logged as a warning; crashes, NaN, broken bindings or presets, empty scenes and larger disagreements trigger a repair.
- **Trace:** every model call logs prompt / completion / reasoning tokens, OpenRouter generation id, finish reason and seconds;
  every validation logs the checks that passed and the failures; repairs log which blocks were replaced. No credentials,
  no hidden reasoning.

## Example input / output (real run)

Generated by `deepseek/deepseek-v4.1-flash` with the committed code (each folder holds `index.html`, `trace.jsonl`,
`reply.txt`; the URL-only run also `excerpt.txt`). All three exited 0 with the review stage run:

| Input | Output | Requests | Tokens (total / completion) | Time |
|---|---|---|---|---|
| `examples/entropy.json` | `examples/showcase/entropy/` | 4: generate, review, repair, review | 32,528 / 7,968 | 66 s |
| `examples/attention.json` | `examples/showcase/attention/` | 5: generate, 2 reviews, 2 repairs | 50,083 / 14,017 | 52 s |
| `examples/attention_url_only.json` | `examples/showcase/attention_url_only/` | 6: excerpt search (3.4k tokens), generate, 2 reviews, 2 repairs | 55,234 / 13,132 | 55 s |

The review stage accounts for 10–24k of these tokens; before it existed the same cases took 9–17k tokens.

Assessed outputs are generated afresh.

## Tests

```sh
python -m unittest discover -s tests -v                     # offline; the model is stubbed
python -m validator.runtime template/fixtures/entropy.txt  # stage 1 checks on one saved reply (no model)
```

## Repository

| Path | Purpose |
|---|---|
| `agent.py` | CLI, OpenRouter client with budgets, excerpt retrieval, generate → validate → repair loop, trace |
| `template/` | page template, kit, math helpers, prompt, assembler (see `template/README.md`) |
| `validator/` | runtime checks, review against the paper, calculator; `python -m validator` validates a saved reply |
| `education_requirements.md` | the teaching rubric the review grades against |
| `HACKATHON.md`, `AGENTS.md`, `CLAUDE.md` | requirements transcription and guidance for coding agents |
| `template/fixtures/` | hand-written replies for the two public practice cases: the one-shot format example in the prompt and test data |
| `examples/` | practice inputs (paraphrased excerpts) and the showcase output |
| `tests/` | offline tests of the agent loop |

## Credits

- [QuickJS](https://bellard.org/quickjs/) via the `quickjs` Python binding (MIT) runs generated JavaScript for checks.
- Visual style inspired by 3Blue1Brown and the Manim colour palette; no code, fonts or assets were copied. All page code
  (HTML, CSS, `kit.js`, `mathlib.js`) was written for this project with AI coding assistants (Claude Code, Codex).
- OpenRouter chat-completions API. Practice sources: Shannon, *A Mathematical Theory of Communication*, Section 6;
  Vaswani et al., *Attention Is All You Need*, Section 3.2.1.
