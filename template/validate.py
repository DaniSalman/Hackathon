"""Deterministic checks for a model reply before it is shipped (no API calls, no browser).

    python -m template.validate template/fixtures/attention.txt

Checks: required blocks and JSON parse; control/preset/scene consistency; render() only calls
known kit components and targets existing scenes; compute() runs on defaults, presets and test
states without throwing or producing NaN/Infinity in numbers it returns; numeric tests pass;
live checks hold on defaults and presets. Uses QuickJS when installed, otherwise Node (dev only).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .assemble import loads_lenient, parse_reply

HERE = Path(__file__).resolve().parent
KIT_FUNCS = {"bars", "matrix", "plot", "plane", "graph", "steps", "readout", "formula", "note", "text", "svg", "fmt", "sub", "color", "palette"}
CTL_TYPES = {"slider", "toggle", "select", "vector", "simplex", "matrix", "play", "range", "number", "checkbox", "boolean"}

HARNESS = r"""
var __out = (function (cases) {
  function bad(v, path) {               // first non-finite number inside a returned value
    if (typeof v === 'number') return isFinite(v) ? null : path;
    if (Array.isArray(v)) { for (var i = 0; i < v.length && i < 500; i++) { var b = bad(v[i], path + '[' + i + ']'); if (b) return b; } }
    else if (v && typeof v === 'object') { for (var k in v) { var b2 = bad(v[k], path + '.' + k); if (b2) return b2; } }
    return null;
  }
  return cases.map(function (c) {
    var res = { name: c.name };
    try {
      var r = compute(JSON.parse(JSON.stringify(c.state)));
      res.nonfinite = bad(r, 'r');
      if (c.expect) res.got = Object.keys(c.expect).reduce(function (o, k) { o[k] = r[k]; return o; }, {});
      if (typeof checks !== 'undefined') res.checks = checks.map(function (ck) {
        try { return { label: ck.label, ok: !!ck.test(c.state, r) }; } catch (e) { return { label: ck.label, ok: false, error: String(e.message || e) }; }
      });
    } catch (e) { res.error = String(e && e.message || e); }
    return res;
  });
})(__CASES__);
var __out_json = JSON.stringify(__out);
"""


def _run_js(source: str) -> str:
    try:
        import quickjs  # type: ignore
        ctx = quickjs.Context()
        ctx.set_time_limit(2)
        ctx.set_memory_limit(64 * 1024 * 1024)
        return ctx.eval(source)
    except ImportError:
        node = shutil.which("node")
        if not node:
            raise RuntimeError("no JavaScript engine: install quickjs (pip) or node")
        proc = subprocess.run([node, "-e", source + "\n;process.stdout.write(__out_json)"], capture_output=True, text=True, timeout=10)
        if proc.returncode:
            raise RuntimeError(proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "node failed")
        return proc.stdout


def _close(a, b, tol) -> bool:
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(a - b) <= tol * max(1.0, abs(a), abs(b))
    return a == b


def _defaults(controls: list[dict]) -> dict:
    state = {}
    for c in controls:
        v = c.get("value")
        if c.get("type") == "select" and v is None and c.get("options"):
            op = c["options"][0]
            v = op.get("value") if isinstance(op, dict) else op
        state[str(c.get("id"))] = v
    return state


def validate(reply: str) -> dict:
    """Return {'ok': bool, 'failures': [...], 'passed': [...]} for one model reply."""
    fails, passed = [], []
    parts = parse_reply(reply)
    for tag in ("content", "controls", "compute", "render"):
        if tag not in parts:
            fails.append(f"missing <{tag}> block")
    if fails:
        return {"ok": False, "failures": fails, "passed": passed}
    try:
        content = loads_lenient(parts["content"], {})
        controls = loads_lenient(parts["controls"], [])
        tests = loads_lenient(parts.get("tests"), [])
    except (json.JSONDecodeError, ValueError) as e:
        return {"ok": False, "failures": [f"invalid JSON: {e}"], "passed": passed}

    ids = [str(c.get("id")) for c in controls]
    if len(controls) < 2:
        fails.append("fewer than 2 controls")
    for c in controls:
        if str(c.get("type", "slider")).lower() not in CTL_TYPES:
            fails.append(f"control {c.get('id')}: unknown type {c.get('type')}")
    scenes = [str(s.get("id")) for s in content.get("scenes", [])] or ["s1"]
    exps = content.get("explorations", [])
    if len(exps) < 2:
        fails.append("fewer than 2 explorations")
    for i, ex in enumerate(exps):
        for k in ex.get("preset", {}):
            if k not in ids:
                fails.append(f"exploration {i + 1}: preset sets unknown control '{k}'")
        if ex.get("focus") and str(ex["focus"]) not in scenes:
            fails.append(f"exploration {i + 1}: focus '{ex['focus']}' is not a scene")
        for f in ("predict", "observe", "why"):
            if not ex.get(f):
                fails.append(f"exploration {i + 1}: missing '{f}'")
    for f in ("title", "hook", "why", "symbols", "equation", "misconception", "grounding"):
        if not content.get(f):
            fails.append(f"content: missing '{f}'")
    g = content.get("grounding", {})
    if not g.get("section") or not g.get("from_paper") or not g.get("simplifications"):
        fails.append("grounding needs section, from_paper and simplifications")

    render = parts["render"]
    for fn in sorted(set(re.findall(r"\bkit\.([A-Za-z_]\w*)", render)) - KIT_FUNCS):
        fails.append(f"render uses unknown kit.{fn}")
    for target in set(re.findall(r"kit\.\w+\(\s*['\"]#?([\w-]+)['\"]", render)):
        if target not in scenes:
            fails.append(f"render targets '#{target}', which is not a scene id")
    if not passed and not fails:
        passed.append("structure")

    base = _defaults(controls)
    cases = [{"name": "defaults", "state": base}]
    for i, ex in enumerate(exps):
        cases.append({"name": f"exploration {i + 1}", "state": {**base, **ex.get("preset", {})}})
    for i, t in enumerate(tests):
        cases.append({"name": f"test {i + 1}", "state": {**base, **t.get("state", {})}, "expect": t.get("expect", {}), "tol": t.get("tol", 1e-6)})

    src = (HERE / "mathlib.js").read_text(encoding="utf-8") + "\n" + parts["compute"] + "\n" + parts.get("checks", "") + "\n" + \
        HARNESS.replace("__CASES__", json.dumps(cases)) + "\n__out_json;"
    try:
        results = json.loads(_run_js(src))
    except Exception as e:  # syntax errors, timeouts, engine failures
        fails.append(f"compute/checks could not run: {e}")
        return {"ok": False, "failures": fails, "passed": passed}
    for case, res in zip(cases, results):
        name = res["name"]
        if res.get("error"):
            fails.append(f"{name}: compute threw: {res['error']}")
            continue
        if res.get("nonfinite"):
            fails.append(f"{name}: non-finite number at {res['nonfinite']}")
        for ck in res.get("checks", []):
            if not ck["ok"]:
                fails.append(f"{name}: live check failed: {ck['label']}" + (f" ({ck['error']})" if ck.get("error") else ""))
        for k, want in case.get("expect", {}).items():
            got = res.get("got", {}).get(k)
            if not _close(got, want, case.get("tol", 1e-6)):
                fails.append(f"{name}: expected {k} = {json.dumps(want)}, got {json.dumps(got)}")
            else:
                passed.append(f"{name}: {k}")
    return {"ok": not fails, "failures": fails, "passed": passed}


if __name__ == "__main__":
    report = validate(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    sys.exit(0 if report["ok"] else 1)
