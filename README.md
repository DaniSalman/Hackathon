# Paper to Playground

A preliminary hackathon implementation: a reusable Python 3.11 agent that turns a supplied research excerpt and learning brief into one offline interactive HTML explanation. No paper-specific solution is selected or embedded by the generator.

## Run

```sh
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export OPENROUTER_API_KEY='your-key'
python agent.py --input examples/entropy.json --output out --model anthropic/claude-sonnet-4
python -m http.server 8000 --directory out
```

Open http://localhost:8000. The local server is optional for viewing; generation requires no server, Node, GPU, browser installation or build step. Use the instructor's exact MODEL_ID for assessment. `anthropic/claude-sonnet-4` is an example development identifier; verify availability in your OpenRouter account. All calls go to https://openrouter.ai/api/v1/chat/completions with the provided model; no model substitution.

Input strings: `source_url`, `focus`, `audience`, and `excerpt`. Also accepts `source_excerpt`, `paper_excerpt` or `source_text` as an excerpt alias. The brief says five required strings but names only three; its assessment section says excerpts are supplied. This implementation requires the excerpt explicitly and never pretends to have fetched a source URL. Only OpenRouter is contacted. Confirm the final case schema with the instructor.

## Architecture

1. Validate input, source URL and focused excerpt.
2. Ask the model for a teaching plan grounded in that excerpt.
3. Generate a structured explanation plus a pure JavaScript calculation function.
4. Validate schema, execute default/exploration cases, and run numerical assertions in QuickJS with 300 ms / 16 MB limits per execution.
5. Ask the same supplied model to review scientific fidelity and teaching content.
6. Feed concrete failures back for up to two autonomous revisions, then render a generic template.

The template provides editable numeric, Boolean, vector and matrix controls; live signed bar charts, matrix heatmaps, intermediate metrics, exploration presets, citations, limitations, accessible labels, responsive layout and explicit error feedback. Calculations run in a terminable Web Worker. Text is inserted via textContent, source JSON escapes script boundaries, and CSP blocks networking.

Budget: 570-second process deadline on Unix, at most 8 API requests, and 29,000 reserved completion tokens including failed requests. No automatic HTTP retries. Actual per-call token usage is required and logged; missing usage fails rather than fabricating accounting. No credentials or hidden model reasoning are logged.

Outputs: `index.html`, `trace.jsonl`, plus inspectable `plan.json` and `spec.json`. Exit 0 means checks and review passed; failures return nonzero with a trace. Use a fresh output directory. Generated content is never hand-edited by the pipeline.

## Checks and remaining work

```sh
python -m unittest discover -s tests -v
```

QuickJS checks execute the actual generated computation, but are not Chromium DOM tests. Numerical test oracles are proposed by the model and reviewed by a model; they are not a proof of scientific correctness. Controls have generic input validation; domain-specific validation belongs in the generated compute function.

**Not submission-ready yet:** no OpenRouter key was available during implementation, so live generation, model quality and a genuine generated example input/output pair remain unverified. Run both practice cases, inspect their pages in Chromium, add one freshly generated output under `examples/showcase/`, and run unseen cases before freezing the repository. The practice case excerpts are labeled paraphrases. No paper-specific prewritten page is included. Browser automation, richer curve/diagram renderers, and independently derived oracle tests are worthwhile next improvements.

## Requirements coverage

- Python 3.11, root agent.py, pinned requirements: implemented.
- Required CLI, supplied OpenRouter model and environment key: implemented.
- Identify / plan / generate / check / revise: implemented.
- Offline single-file output, two controls, two explorations, source grounding: enforced by schema and prompts.
- Actual calculations, boundary tests, trace and usage accounting: implemented.
- Live assessed generation and example output: pending API key.
- GitHub URL, final commit SHA, instructor access: submission tasks remain.

## Team and credits

Team members: fill in before submission. Implementation assisted by Codex. QuickJS Python bindings (quickjs==1.19.4) provide the calculation sandbox; Python standard library provides HTTP, CLI and JSON. Generic HTML/CSS/SVG renderer authored for this project. No external visual assets or copied paper-specific implementations. Practice sources: Shannon, *A Mathematical Theory of Communication*, Section 6; Vaswani et al., *Attention Is All You Need*, Section 3.2.1. OpenRouter API format: https://openrouter.ai/docs/quickstart.
