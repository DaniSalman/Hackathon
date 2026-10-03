"""Assemble a self-contained page from a model reply and the generic 3b1b-style template.

The model reply uses tagged blocks:
    <content>{...JSON...}</content>      text, symbols, scenes, explorations, grounding
    <controls>[...JSON...]</controls>    control specs (slider, toggle, select, vector, simplex, matrix, play)
    <compute>function compute(s) {...}</compute>
    <render>function render(s, r, kit) {...}</render>
    <checks>const checks = [...];</checks>   live invariants shown on the page
    <tests>[...JSON...]</tests>          numeric oracles for the Python-side QuickJS checks

Usage:  python -m template.assemble fixtures/entropy.txt out/index.html [--case case.json]
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TAGS = ("content", "controls", "compute", "render", "checks", "tests")
_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*\n?|\n?\s*```\s*$")
_SLOT = re.compile(r"/\*__([A-Z]+)__\*/|__TITLE__")


def parse_reply(text: str) -> dict[str, str]:
    """Extract the tagged blocks (missing tags are simply absent)."""
    parts = {}
    for tag in TAGS:
        m = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", text, re.S | re.I)
        if m:
            parts[tag] = _FENCE.sub("", m.group(1)).strip()
    return parts


def loads_lenient(block: str | None, default):
    """json.loads that tolerates trailing commas; returns default when empty."""
    if not block:
        return default
    try:
        return json.loads(block)
    except json.JSONDecodeError:
        return json.loads(re.sub(r",\s*([\]}])", r"\1", block))


def _json_for_script(data) -> str:
    # '<' only appears inside JSON strings, where < is a valid escape: no </script> break-out.
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")


def _code_for_script(code: str) -> str:
    return re.sub(r"</(script)", r"<\\/\1", code, flags=re.I).replace("<!--", "<\\!--")


def build_page(parts: dict[str, str], case: dict | None = None) -> str:
    """Return the final single-file HTML for parsed reply parts."""
    data = loads_lenient(parts.get("content"), {})
    data["controls"] = loads_lenient(parts.get("controls"), [])
    if case and case.get("source_url"):
        data["source_url"] = case["source_url"]  # trusted input, never taken from the model
    code = "\n\n".join(parts.get(k, "") for k in ("compute", "render", "checks") if parts.get(k))
    files = {
        "STYLE": (HERE / "style.css").read_text(encoding="utf-8"),
        "MATHLIB": (HERE / "mathlib.js").read_text(encoding="utf-8"),
        "KIT": (HERE / "kit.js").read_text(encoding="utf-8"),
        "DATA": _json_for_script(data),
        "GENERATED": _code_for_script(code),
    }
    title = html.escape(re.sub(r"[{}]", "", str(data.get("title") or "Interactive explanation")))
    page = (HERE / "page.html").read_text(encoding="utf-8")
    return _SLOT.sub(lambda m: title if m.group(0) == "__TITLE__" else files.get(m.group(1), m.group(0)), page)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    case = None
    if "--case" in argv:
        i = argv.index("--case")
        case = json.loads(Path(argv[i + 1]).read_text(encoding="utf-8"))
        argv = argv[:i] + argv[i + 2:]
    reply = Path(argv[0]).read_text(encoding="utf-8")
    out = Path(argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_page(parse_reply(reply), case), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
