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
| `fixtures/*.txt` | hand-written replies for the public examples; `entropy.txt` doubles as the one-shot example |
| `assemble.py` | `parse_reply(text)` + `build_page(parts, case)` → single self-contained HTML (CSP blocks all network) |
| `validate.py` | `validate(reply)` → structure checks + runs compute/tests/live checks in QuickJS (Node fallback for local dev) |
| `prompting.py` | `system_prompt()` and `user_prompt(case)` |

## Pipeline integration (one generation call, validate, targeted repair only on failure)

```python
from template.prompting import system_prompt, user_prompt
from template.assemble import parse_reply, build_page
from template.validate import validate

reply = call_model([{"role": "system", "content": system_prompt()},
                    {"role": "user", "content": user_prompt(case)}])
report = validate(reply)            # report["failures"] is a list of concrete messages to send back on repair
html = build_page(parse_reply(reply), case)
```

## Try it locally

```bash
python -m template.assemble template/fixtures/attention.txt demos/attention.html --case examples/attention.json
python -m template.validate template/fixtures/attention.txt
python -m http.server 8765 --directory demos
```

Pages to look at: `demos/entropy.html` (single-scene explorer) and `demos/attention.html` (four-scene walkthrough).
Things to try: drag the probability bars or the arrow tips, hover any matrix cell (linked highlights across scenes),
press "Try it" on an exploration, toggle scaling.
