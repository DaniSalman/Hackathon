# Paper to Playground

A reusable Python 3.11 agent that turns a focused research-paper excerpt and a learning brief into one
self-contained, interactive HTML explanation, paced one idea at a time in a style inspired by 3Blue1Brown.

**Team:** Dani Salman, Ibrahim, Samer *(full names to be completed)*

**MODEL_ID:** `deepseek/deepseek-v4.1-flash` (via OpenRouter)

The design rule behind everything below:
- **The model writes only the small, paper-specific part. Everything that can be decided by code is decided by code.**
- The model generates once, may be asked to repair at most twice, and may be asked to review the reply against the
  paper at most twice.
- The review never judges numbers itself: it writes formulas, and a deterministic calculator evaluates them.

## Setup and run

```sh
python -m pip install -r requirements.txt          # Python 3.11; no GPU, no system packages, no build step
export OPENROUTER_API_KEY=...                       # read from the environment; never stored, logged or embedded
python agent.py --input examples/entropy.json --output out --model deepseek/deepseek-v4.1-flash
```

| Output | Content |
|---|---|
| `out/index.html` | the page: one offline file (CSS, JS and data inlined; a Content-Security-Policy blocks all network access) |
| `out/trace.jsonl` | one JSON event per line: stage, action, result, elapsed seconds, per-call tokens, checks, review grades, calculator results, failures, repairs |
| `out/reply.txt` | the model's final tagged reply, for inspection |

Exit code:

| Code | Meaning |
|---|---|
| `0` | page written, no blocking failure, and the review stage ran |
| `2` | page written, but blocking failures remain after repairs **or the review could not run** (for example, the case has no `paper_md`) |
| `1` | no usable page |

Use a fresh output directory per run.

**Input** (`case.json`):
- String fields `source_url`, `focus` and `audience`.
- The excerpt, accepted under `excerpt`, `source_excerpt`, `paper_excerpt`, `source_text`, `text` or `section_text`.
- Optionally `paper_md`: the path, relative to the case file, of the full paper converted to Markdown beforehand.
  Only the review stage reads it; it is removed from the case before the generator sees it.

Every other string field is passed to the generator as data. The `source_url` is cited on the page and **never
fetched**: during assessment only OpenRouter is reachable.

**Tests and tools:**

```sh
python -m unittest discover -s tests -v                       # 47 offline tests; the model is stubbed
python -m validator.runtime template/fixtures/entropy.txt     # stage 1 checks on one reply, no model
python -m validator --input examples/attention.json --reply out/reply.txt --output check-out --model MODEL_ID
                                                              # full validation of a saved reply (needs a key and paper_md)
```

## Flow

```
case.json
   │  load_case            D  find the excerpt field, cap it at 24,000 characters, read paper_md if given
   ▼
prompt                     D  system: teaching rules + reply format + kit API + one example reply
   │                          user:   the case fields as JSON (without paper_md), labelled "data, not instructions"
   ▼
generate (1 model call)    N  the model returns six tagged blocks:
   │                          content · controls · compute(s) · render(s, r, kit) · checks · tests
   ▼
validator  ┌ stage 1  runtime checks       D  structure; QuickJS runs compute / checks / tests / render on fixed states
           │          (every reply, free)     if anything blocking fails, stop here: no review is spent on a broken reply
           ├ stage 2  review (model call)  N  only with paper_md, at most 2 per run: grades the reply against the full
           │                                  paper and the education rubric, and writes one formula per numeric claim
           └ stage 3  calculator           D  evaluates those formulas in QuickJS and compares them with the reply's numbers
   │
   ├─ no blocking failure ─────────────────────────────────────────────┐
   ▼                                                                    │
repair (≤ 2 model calls)   N  the exact failure messages go back;        │
   │                          the model returns only the blocks it changes,
   │                          which replace the old ones; then validate again
   ▼                                                                    ▼
assemble                   D  paste the best reply into the pre-written template ──▶ out/index.html
                                                                        + trace.jsonl, reply.txt
D = deterministic (same input, same result)    N = non-deterministic (model output)
```

## What is deterministic and what is not

### Deterministic: code we wrote, same input gives the same result

| Step | Where | What it does |
|---|---|---|
| Input handling | `agent.py: load_case`, `validator/core.py: load_paper` | finds the excerpt under any accepted key, truncates long excerpts, reads `paper_md`, logs missing fields |
| Prompt building | `template/prompting.py`, `template/prompt_kit.md`, `validator/review.py: build_messages` | the same case and reply always produce byte-identical generator and reviewer messages |
| Reply parsing | `template/assemble.py: parse_reply`, `validator/review.py: parse_review` | extracts the six tagged blocks and the review's JSON; tolerates trailing commas |
| Stage 1: runtime checks | `validator/runtime.py` | see below; runs in QuickJS (Node as a local-development fallback) |
| Stage 3: calculator | `validator/calculator.py` | evaluates the reviewer's formulas with its own helpers, independent of the page's `mathlib.js`, so a bug shared by the page and the reference cannot hide a wrong number |
| Verdict | `validator/core.py`, `validator/review.py: findings`, `agent.py: blocking, score` | the host, not the model, decides pass or fail, which failures block, which review findings are withheld, and which reply is the best so far |
| Page assembly | `template/assemble.py: build_page` | fills `page.html` with the CSS, kit, data and generated code; escapes `</script>`; takes `source_url` from the case, never from the model |
| The page itself | `template/kit.js`, `template/mathlib.js` | every number on the page is computed live by `compute()` from the control values; the same inputs always show the same numbers |

**Stage 1, runtime checks** (on every reply, no model call):

1. **Structure:** all required blocks and fields exist; at least 2 controls and exactly 2 explorations with predict,
   observe and why; presets, focus scenes and control scenes point at things that exist; grounding has a section,
   `from_paper` statements and `simplifications`; `render` uses only real kit functions.
2. **Computation:** `compute` runs on the defaults, every exploration preset and every test state without throwing or
   returning NaN; each test's expected values match (0.1 % default tolerance); the live `checks` hold.
3. **Rendering:** `render` runs against a mock kit on the same states: every panel targets an existing scene, every
   scene gets a panel, no NaN reaches a visual, no "undefined"/"NaN" appears in text, and draggable visuals are bound to
   controls of the right type.

A test value off by at most 5 %, or a live check failing only in an extreme test state, is logged as a warning and
does not trigger a repair. Everything else blocks, and a reply that blocks at stage 1 is never sent to review.

**Stage 3, calculator:** the reviewer writes one entry per numeric claim. That means each number in captions,
"why", "observe" and the misconception, and each test expectation, up to 30 entries. Every entry carries a formula
taken from the paper and written over the page's control variables. The calculator:
- runs each formula in the exact page state the claim describes: the defaults, plus the exploration preset or the test state;
- compares the result with the reply's number;
- turns a mismatch into a failure for the generator to repair;
- logs and discards entries that are unusable (bad path, misquote, formula error), never blaming the generator for them.

A review finding is **withheld** if it states a number found nowhere in the reply or the paper, or disputes a number
the calculator verified. When no review budget is left, the stored entries are rechecked for free.

### Non-deterministic: everything a model produces

| What varies | Why | Effect we measured |
|---|---|---|
| The generated reply (text, controls, code, tests) | sampling at the provider's default temperature; no seed is set; OpenRouter routes the request (sorted by throughput) to one of several providers | two runs of the same case produced different scenes and controls |
| The review (grades, issues, which formulas it writes) | the same sampling, on a second model call | not yet measured |
| Whether a repair is needed | depends on the reply and the review | the same case took 2 calls once and 3 calls the next time |
| Tokens and latency | follow from the above; providers differ in speed (one call took 34 s on one provider and 217 s on another) | the same case cost 15.2k tokens / 38 s, then 26.2k tokens / 50 s |
| Budget decisions | a repair is skipped when fewer than 120 s or 3,000 completion tokens remain; a review needs 90 s and 3,000 tokens | not triggered in our runs |
| Transport | one automatic retry on network errors, HTTP 429 or 5xx | not triggered in our runs |

Run-to-run variation is contained by the deterministic layer:
- every reply passes through the same runtime checks;
- every number the review questions is settled by the calculator;
- the page that ships is always the best-scoring reply seen.

### What the checks cannot prove

- **The reviewer's formula is still model-written.** The calculator removes model arithmetic from the verdict, but if
  the reviewer copies the wrong equation, a wrong number can pass. Before the review stage existed, a FedAvg practice
  run shipped an incorrect local-update formula because a repair changed the test to match `compute`. The calculator
  is designed to catch that kind of error, provided the reviewer takes the right formula from the paper.
- **The review only runs when the case has `paper_md`.** Without it, only stage 1 runs and the run ends with exit 2.
- **Controls that change nothing.** No check confirms that every control affects the output.
- **Visual quality in a real browser.** `render` runs against a mock kit, not in Chromium.

## Efficiency: why the model writes so little code

| Design choice | Effect |
|---|---|
| **Pre-written template.** Layout, theme, components (bars, matrix, plot, 2-D plane, graph, steps, readout, formula), controls, dragging, animation, live checks and staged reveal live in `template/` (about 138k characters). | The generator's reply is 7–14 % of the final page (11k–23k characters out of about 150k). No tokens are spent on HTML, CSS or drawing code. |
| **Small model-facing API.** `compute(s)` is the formula; `render(s, r, kit)` is a short list of kit calls such as `kit.bars('#s1', r.p, {...})`. | `compute` and `render` are usually 20–60 lines each. |
| **One generation call, no plan call.** The reply's scenes, controls and explorations are the plan. | 1 call when the first reply passes (water-filling practice case: 9.5k tokens, 18 s). |
| **Free checks before paid ones.** Stage 1 and the calculator cost no tokens; the review runs only after stage 1 passes. Once the review budget is spent, the stored formulas are rechecked for free. | A broken reply never costs a review call. |
| **Targeted repair.** Failures go back verbatim and the model returns only the blocks it changes. The repair prompt drops the example reply (5.6k instead of 12.8k characters). | A repair that only fixes `tests` costs about 200–1,500 completion tokens. |
| **Reasoning off by default** for generation and review (`P2P_REASONING=off`). | Measured on the practice cases: `low` reasoning cost 19–37k tokens and 80–225 s per case; `off` cost 9–17k tokens and 24–41 s with equally correct pages. With `minimal`, the review spent its whole 5,000-token cap reasoning over a full paper. |
| **Fast providers first** (`P2P_PROVIDER_SORT=throughput`). | Avoids the slow providers serving the same model. |
| **Shared math library.** `M.softmax`, `M.xlog2x` (with 0·log 0 = 0), `M.matmul` and similar helpers exist on both the page and in QuickJS. | The model does not re-implement numerics, and edge cases like zero probabilities behave the same everywhere. |
| **Budgets inside the limits.** Up to 9 requests (generate, one re-ask, 2 repairs, 2 reviews, 3 retries; limit 10), 29,000 reserved completion tokens (limit 30,000), 560 s deadline (limit 600 s). | The run always ends in time with the best page so far. |

**The largest prompt is the review.** It carries the whole `paper_md`, plus the education rubric, the kit API and the
reply. For the min-p paper, the converted full text alone is about 119k characters, roughly 30k prompt tokens per
review call. The next section proposes how to cut that.

## Suggested extension: a deterministic HTML → Markdown converter instead of an LLM reading the paper

*This is a proposal.* The converter, `arxiv_to_markdown.py`, exists on the `Samer` branch, where it was used to
build our practice cases; it is not on `main` yet. During assessment the excerpt comes with the case and only
OpenRouter is reachable. The review stage, however, already expects `paper_md`, "the full paper, converted
beforehand". That is exactly what this converter produces, with no model.

### What it does

arXiv publishes an HTML version of most recent papers, generated from the LaTeX source by LaTeXML. Every formula in
that HTML is a `<math>` element whose `alttext` attribute holds the author's original LaTeX. The converter parses the
page with Beautiful Soup and emits Markdown:

- formulas are copied **exactly** from the LaTeX source, as `$...$` and `$$...$$ (n)` with their equation numbers;
- headings, lists, footnotes and algorithm blocks are kept;
- tables become regular Markdown tables, with merged cells expanded into a grid;
- figures are replaced by their captions;
- colour commands and other presentation-only markup are removed.

No model is involved: **the same HTML always gives the same Markdown.** Each conversion also produces a self-check
report: formulas written versus formulas in the source, and the share of the source's words found in the output.

On 11 papers with very different layouts (Attention, Mamba, DPO, Mixtral, LoRA, ViT, GPT-3, min-p, adversarial
water-filling, GAN and FedAvg), every formula was written and text coverage was 100 %. Only words drawn inside
images are lost, and the report lists those separately.

```python
from arxiv_to_markdown import arxiv_to_markdown
result = arxiv_to_markdown("1706.03762v7", write=False)    # fetches https://arxiv.org/html/1706.03762v7
print(result.report.summary())                             # formulas 142/142, text coverage 100 %, ...
```

### Why being deterministic means fewer LLM calls

Whenever the pipeline needs paper text, whether for `paper_md` or for a case without an excerpt, it can get it with
a model or with this code:

| | An LLM reads the paper (e.g. OpenRouter's PDF parser + the model) | Deterministic converter |
|---|---|---|
| Extra model calls | at least 1 to read or extract the text | **0** |
| Extra tokens | the parsed paper is prompt input on every call that carries it; a transcription would also cost completion tokens (a Markdown copy of *Attention Is All You Need* is about 41k characters, roughly 10–12k tokens, a third or more of the 30k completion limit) | **0** |
| Formulas | re-typed by the model or recovered by OCR from the PDF, so they can be wrong | copied from the author's LaTeX, which is what the reviewer's calculator formulas should be taken from |
| Same output on every run | no | yes |
| Can code check it? | no, the text is whatever the model produced | yes, the self-check report counts every formula and word |

Fewer tokens and calls score directly, because token efficiency and latency are 15 of the 100 points. The determinism
also saves calls later in the pipeline:

1. **A fixed, exact text removes one source of repairs.** The generator and the reviewer see the real LaTeX instead
   of a paraphrase or an OCR guess, so there is less room for a misread formula in `compute`, `tests` or a calculator
   entry. We expect this to reduce repair calls; we have not measured it yet.
2. **Grounding can be checked by code.** Because the text is known exactly, the `from_paper` statements and quoted
   equations in the reply can be matched against it by string comparison, without spending review tokens on it.
3. **Runs become comparable.** With the input fixed, any difference between two runs comes from the model alone. This
   makes it possible to measure prompt or validator changes on the same cases.

### Sending only the relevant part: section selection by similarity

Converting the paper is only half the saving: the whole paper is still a lot of prompt, and the review resends it on
every review call. Because the converter keeps the headings, the Markdown splits cleanly into sections. We can then
keep only the sections that match the brief, and skip the rest **before** anything reaches OpenRouter:

1. Split the converted paper at its headings. Represent each section by its heading path plus its first sentence,
   for example `3 Model Architecture > 3.2 Attention > 3.2.1 Scaled Dot-Product Attention: We call our particular
   attention...`.
2. Embed the query (the `focus`, plus the excerpt when one is supplied) and every section representation. All
   section representations go in one batched request.
3. Compute the cosine similarity between the query and each section. **Similar: keep the whole section. Not
   similar: skip it.** Use a threshold, or keep the top few sections.
4. Always keep the parent section's opening paragraph, where symbols are usually defined. Cap the total length.

What this saves, measured on two papers we converted:

| Paper | Whole paper | Headings to embed | Relevant sections kept |
|---|---|---|---|
| *Attention Is All You Need* | 41k characters, about 10.3k tokens | 31 headings, about 190 tokens | §3.2 and §3.2.1: 2.0k characters, about 0.5k tokens (**4.9 %**) |
| Min-p sampling (arXiv 2407.01082) | 119k characters, about 29.7k tokens | 121 headings, about 1.0k tokens | §3, §3.1 and §3.2: 3.9k characters, about 1.0k tokens (**3.3 %**) |

Applied to `paper_md`, this would cut the review prompt for min-p from about 30k tokens of paper to about 1k, on each
of up to two review calls. Selection must happen on our side because we hold the text: with OpenRouter's PDF parser,
the whole parsed paper goes into the prompt and the model pays for all of it.

Caveats:

- **The brief's model rule.** The brief says all model calls must use the supplied MODEL_ID. An embedding model is a
  different model, so an OpenRouter embeddings call is probably not allowed during assessment. It would also use one of
  the 10 requests, and its tokens would count. The assessment-safe variant replaces embeddings with **lexical scoring**,
  such as TF-IDF or BM25 over the words of `focus` and each section. That is a few lines of pure Python, deterministic,
  needs no model and no API call, and does the same keep-or-skip selection. Embeddings remain useful during development
  and for paraphrased briefs, where the words differ but the meaning matches.
- **Headings alone are weak signals.** The min-p paper has several sections titled just "Setup" or "Results". That is why
  step 1 embeds the full heading path plus the first sentence, not the bare heading.
- **The threshold must be tuned, and we can test it automatically.** Our four practice cases have hand-picked verbatim
  excerpts, so we can check in code whether the selected sections contain every excerpt paragraph. That measures recall
  without any model.

### How it would plug in

1. **Produce `paper_md` with the converter.** 0 model calls, exact formulas. This is what the review stage already
   expects.
2. **Trim `paper_md` to the sections that match `focus`**, as described above, to cut the review's prompt by about 95 %.
3. **If a case arrives without an excerpt and arxiv.org is reachable:** in `load_case`, convert `source_url` and keep
   only the matching sections. That is 0 model calls with lexical scoring, or 1 batched embeddings request, compared
   with 1 or more full-paper model calls.
4. **Grounding check:** extend `validator/runtime.py` so it fails a reply whose `from_paper` statements do not appear
   in the excerpt. This also requires no model call.

Limits: it needs arXiv's HTML version (most papers since late 2023 and many older ones; not PDF-only sources like
the Shannon paper in public Example B), and it needs network access to arxiv.org.

## Example input / output (real runs)

Generated by `deepseek/deepseek-v4.1-flash` (`index.html`, `trace.jsonl` and `reply.txt` in each folder), measured
before the review stage was added:

| Input | Output | Calls | Tokens | Time |
|---|---|---|---|---|
| `examples/entropy.json` | `examples/showcase/entropy/` | 1 (all checks passed first time) | 8,916 | 37 s |
| `examples/attention.json` | `examples/showcase/attention/` | 2 (first reply had NaN in the output row; one repair) | 16,918 | 29 s |

Assessed outputs are generated afresh.

### Practice cases from other papers

To test unseen-style inputs, we built cases with **verbatim** excerpts cut from each paper's arXiv HTML with the
converter. The two public cases above use short paraphrases. The case files are on the `Samer` branch. They were
measured before the review stage was added:

| Case | Paper | Calls | Tokens | Time | Exit |
|---|---|---|---|---|---|
| `minp.json` | Min-p sampling, arXiv 2407.01082, §3 (two runs) | 2 / 3 | 15.2k / 26.2k | 38 s / 50 s | 0 / 0 |
| `waterfill.json` | Adversarial water-filling, arXiv 2605.26163, §III-A, Eq. (4) | 1 | 9.5k | 18 s | 0 |
| `gan.json` | Generative Adversarial Nets, arXiv 1406.2661, §4.1 | 3 | 35.2k | 83 s | 2 |
| `fedavg.json` | FederatedAveraging, arXiv 1602.05629, §2 | 2 | 27.7k | 85 s | 0 |

## Repository

| Path | Purpose |
|---|---|
| `agent.py` | CLI, OpenRouter client with budgets, generate → validate → repair loop, trace |
| `validator/` | every check on a reply: `runtime.py` (stage 1), `review.py` (stage 2, the reviewer call), `calculator.py` (stage 3), `core.py` (orchestration and verdict) |
| `education_requirements.md` | the teaching rubric the reviewer grades against (8 headings, from section 2 of the brief and the teaching-clarity criterion) |
| `template/` | page template, kit, math helpers, prompt and assembler (see `template/README.md`) |
| `template/fixtures/` | hand-written replies for the two public practice cases: the one-shot format example in the prompt and test data |
| `examples/` | practice inputs and the showcase outputs |
| `tests/` | offline tests of the agent loop, the validator and the calculator |
| `arxiv_to_markdown.py` | *on the `Samer` branch*: the deterministic arXiv HTML → Markdown converter (see "Suggested extension" above); needs `requests`, `beautifulsoup4` and network access to arxiv.org |

## Credits

- [QuickJS](https://bellard.org/quickjs/) via the `quickjs` Python binding (MIT) runs generated JavaScript and calculator formulas.
- [Requests](https://requests.readthedocs.io/) and [Beautiful Soup](https://www.crummy.com/software/BeautifulSoup/) are
  used only by the development converter `arxiv_to_markdown.py`, which reads the LaTeXML-generated HTML that arXiv publishes.
- Visual style inspired by 3Blue1Brown and the Manim colour palette; no code, fonts or assets were copied. All page code
  (HTML, CSS, `kit.js`, `mathlib.js`) was written for this project with AI coding assistants (Claude Code, Codex).
- OpenRouter chat-completions API. Practice sources: Shannon, *A Mathematical Theory of Communication*, Section 6;
  Vaswani et al., *Attention Is All You Need*, Section 3.2.1; Nguyen et al., *Turning Up the Heat: Min-p Sampling*;
  Tong et al., *Adversarial Water-Filling*; Goodfellow et al., *Generative Adversarial Nets*; McMahan et al.,
  *Communication-Efficient Learning of Deep Networks from Decentralized Data*.
