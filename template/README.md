# Visual kit (3Blue1Brown-inspired template)

One generic page template. The model never writes HTML, CSS or animation code: it returns a tagged reply
(content, controls, `compute`, `render`, `checks`, `tests`) and the kit turns it into an interactive page.

| File | What it is |
|---|---|
| `page.html` | page skeleton: hero question, symbol chips, sidebar controls + live checks, scenes, general rule, explorations, takeaway, limitation, sources |
| `style.css` | dark Manim-like theme, symbol colours, motion, responsive layout |
| `kit.js` | components (`bars`, `matrix`, `plot`, `plane`, `graph`, `steps`, `readout`, `formula`, `note`, `svg`), controls, tweening, hover-linking, draggable visuals, guided "Try it" animations |
| `mathlib.js` | `M.*` helpers shared by the page and the QuickJS checks (stable softmax, `xlog2x` with 0·log 0 = 0, matmul, ...) |
| `prompt_kit.md` | system prompt: 3b1b teaching rules + reply contract + kit API (~1.4k tokens) |
| `fixtures/*.txt` | hand-written replies for the two public practice cases: the one-shot format example in the prompt and test data |
| `assemble.py` | `parse_reply(text)` + `build_page(parts, case)` → single self-contained HTML (CSP blocks all network) |
| (moved) | the runtime checks that were `validate.py` now live in `validator/runtime.py`; the validator owns every check |
| `prompting.py` | `system_prompt()` and `user_prompt(case)` |

## Pacing (one idea at a time)

The page reveals itself in stages: scene 1 → Continue → scene 2 → … → general rule → explorations → key idea, limitation and sources.
The model controls the pacing with three optional fields: `scenes[i].pause` (a "pause and ponder" question shown above the
Continue button), `scenes[i].gate: false` (show this scene together with the previous one) and `controls[j].scene` (the input
appears in the sidebar when that scene is revealed). Hidden content stays in the DOM, "Show everything" (top right) or `#all`
in the URL opens every section, and "Try it" unlocks what it needs.

## Pipeline integration (one generation call, validator, targeted repair only on failure)

```python
from template.prompting import system_prompt, user_prompt
from template.assemble import parse_reply, build_page
from validator import Validator

reply = call_model([{"role": "system", "content": system_prompt()},
                    {"role": "user", "content": user_prompt(case)}])
report = Validator(case, case_path, client, trace).check(reply)   # report["failures"]: messages to send back on repair
html = build_page(parse_reply(reply), case)
```

## Try it locally

```bash
python -m template.assemble template/fixtures/attention.txt out/attention.html --case examples/attention.json
python -m validator.runtime template/fixtures/attention.txt
```

Open `out/attention.html` in Chromium. Things to try: press Continue to reveal each scene, drag the arrow tips or
the bars, hover any matrix cell (linked highlights across scenes), press "Try it" on an exploration, toggle scaling.
