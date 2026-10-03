# Coding Agent Entry Point

## Read first

Before planning, editing, or reviewing this repository, read **[HACKATHON.md](HACKATHON.md)** in full. It contains the structured hackathon announcement, required interface, constraints, public examples, scoring, and submission checklist.

Then read **[README.md](README.md)** for the implementation architecture, setup, and known gaps. Inspect the current code before relying on implementation-status claims.

This repository is the standalone **Paper to Playground** hackathon project. Guidance for unrelated projects does not define its architecture or runtime.

## Essential context

- Deliver a reusable Python 3.11 generator, with `agent.py` at the root and pinned dependencies.
- Preserve `python agent.py --input case.json --output out --model MODEL_ID`.
- Use the supplied model through OpenRouter and an environment API key; assessment network access is limited to OpenRouter.
- Generate offline `index.html` and an honest `trace.jsonl` containing actual checks and per-call usage.
- Stay within the organizer's 10-minute, 10-request, and 30,000-completion-token limits per case, including retries where applicable.
- Generate explanations from supplied sources; avoid built-in paper-specific answers. Keep calculations executable and source claims grounded.
- The official input schema is ambiguous. Read HACKATHON.md section 4 before changing input handling; do not present local assumptions as organizer requirements.
- Multiple agents are optional. This file does not require delegation.

## Working conventions

- Follow explicit user instructions; distinguish requested changes from organizer rules and current implementation choices.
- Keep the generator general enough for unseen cases.
- For behavioral changes, run relevant tests. Current suite: `python -m unittest discover -s tests -v`.
- Clearly distinguish mocked model tests, live API runs, computation checks, and actual browser checks.
- Keep credentials out of source, traces, generated pages, and commits.
- Keep README implementation notes current. Update HACKATHON.md only to correct the transcription or record a confirmed clarification.
