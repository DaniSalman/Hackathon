"""Deterministic checks for a model reply before it is shipped (no API calls, no browser).

    python -m template.validate template/fixtures/attention.txt

1. Structure: required blocks parse; >= 2 controls; 2 complete explorations; presets, focus scenes and
   control scenes refer to things that exist; grounding is filled in.
2. compute(): runs on the defaults, every exploration preset and every test state without throwing
   or returning NaN/Infinity; numeric tests match; live checks hold.
3. render(): runs against a mock kit on the same states. Every panel must target an existing scene,
   carry finite numbers, and have no "undefined"/"NaN" in its text; every scene gets a panel; every
   draggable binding points at a control of the right type; plot functions return finite values.
Uses QuickJS when installed (assessment environment), otherwise Node (local development).
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
BIND_TYPES = {"bars": {"vector", "simplex"}, "matrix": {"matrix"}, "plot.marker": {"slider", "play", "range", "number"}, "plane": {"vector"}}

HARNESS = r"""
function __bad(v, path) {               // first non-finite number inside a value
  if (typeof v === 'number') return isFinite(v) ? null : path;
  if (Array.isArray(v)) { for (var i = 0; i < v.length && i < 500; i++) { var b = __bad(v[i], path + '[' + i + ']'); if (b) return b; } }
  else if (v && typeof v === 'object') { for (var k in v) { var b2 = __bad(v[k], path + '.' + k); if (b2) return b2; } }
  return null;
}
var __rec = { calls: [], binds: [], problems: [] };
var __kit = (function () {
  function txt(where, s) { if (typeof s === 'string' && /undefined|NaN|\[object /.test(s)) __rec.problems.push(where + ' shows "' + s.slice(0, 70) + '"'); }
  function rec(fn, t, data, o) {
    o = o || {};
    var id = typeof t === 'string' ? t.replace(/^#/, '') : String(t);
    __rec.calls.push({ fn: fn, target: id });
    var b = __bad(data, 'data'); if (b) __rec.problems.push('kit.' + fn + ' in #' + id + ': non-finite number at ' + b);
    txt('kit.' + fn + ' title', o.title);
    if (Array.isArray(o.labels)) o.labels.forEach(function (l) { txt('kit.' + fn + ' label', String(l)); });
    if (typeof o.tip === 'function') { try { txt('kit.' + fn + ' tooltip', String(o.tip(0, 0, 0))); } catch (e) { __rec.problems.push('kit.' + fn + ' tip() threw: ' + (e.message || e)); } }
    if (o.bind != null) __rec.binds.push({ fn: fn, bind: o.bind });
  }
  function fnSeries(where, f, d) {
    var ok = 0;
    for (var i = 0; i <= 40; i++) {
      try { var y = f(d[0] + (d[1] - d[0]) * i / 40); if (typeof y === 'number' && isFinite(y)) ok++; }
      catch (e) { __rec.problems.push(where + ' fn threw: ' + (e.message || e)); return; }
    }
    if (!ok) __rec.problems.push(where + ' fn never returns a finite number on its domain');
  }
  return {
    bars: function (t, v, o) { rec('bars', t, v, o); },
    matrix: function (t, A, o) { rec('matrix', t, A, o); },
    plot: function (t, o) {
      o = o || {}; var d = o.domain || o.xRange || [0, 1], data = [];
      (o.series || []).forEach(function (s, k) { if (typeof s.fn === 'function') fnSeries('kit.plot series ' + (k + 1), s.fn, s.domain || d); else data.push([s.x || [], s.y || []]); });
      (o.points || []).forEach(function (p) { data.push([p.x, p.y]); });
      if (o.marker) { data.push(o.marker.x); if (o.marker.bind != null) __rec.binds.push({ fn: 'plot.marker', bind: o.marker.bind }); }
      rec('plot', t, data, { title: o.title });
    },
    plane: function (t, o) {
      o = o || {}; var data = [];
      (o.vectors || []).concat(o.points || []).forEach(function (v) { if (v.bind != null) __rec.binds.push({ fn: 'plane', bind: v.bind }); else data.push([v.x, v.y]); });
      (o.segments || []).forEach(function (sg) { data.push([sg.from, sg.to]); });
      (o.polygons || []).forEach(function (pg) { data.push(pg.points); });
      rec('plane', t, data, { title: o.title });
    },
    graph: function (t, o) {
      o = o || {};
      rec('graph', t, [(o.nodes || []).map(function (n) { return n.value == null ? 0 : n.value; }), (o.edges || []).map(function (e) { return e.weight == null ? 0 : e.weight; })], { title: o.title });
    },
    steps: function (t, items, o) {
      items = items || [];
      rec('steps', t, items.map(function (it) { var v = Array.isArray(it) ? it[1] : it && it.value; return typeof v === 'string' ? 0 : v; }), o || {});
      items.forEach(function (it) { if (it && !Array.isArray(it)) txt('kit.steps label', it.label); });
    },
    readout: function (t, o) { o = o || {}; rec('readout', t, [o.value], { title: o.label }); txt('kit.readout note', o.note); },
    formula: function (t, s) { rec('formula', t, [], {}); txt('kit.formula', String(s)); },
    note: function (t, s) { rec('note', t, [], {}); txt('kit.note', String(s)); },
    text: function (t, s) { rec('note', t, [], {}); txt('kit.text', String(s)); },
    svg: function (t, draw, o) {
      var nums = [], g = {};
      ['line', 'arrow', 'circle', 'rect', 'text', 'path', 'polygon'].forEach(function (k) {
        g[k] = function () { for (var i = 0; i < arguments.length; i++) if (typeof arguments[i] === 'number' || Array.isArray(arguments[i])) nums.push(arguments[i]); };
      });
      g.x = function (v) { return v; }; g.y = function (v) { return v; }; g.fmt = M.fmt; g.color = function () { return '#ffffff'; };
      try { draw(g); } catch (e) { __rec.problems.push('kit.svg drawing threw: ' + (e.message || e)); }
      rec('svg', t, nums, o || {});
    },
    fmt: M.fmt, sub: M.subDigits, color: function () { return '#ffffff'; }, palette: {}
  };
})();
var __out = (function (cases) {
  var clone = function (v) { return JSON.parse(JSON.stringify(v)); };
  return cases.map(function (c) {
    var res = { name: c.name };
    try {
      var r = compute(clone(c.state));
      res.nonfinite = __bad(r, 'r');
      if (c.expect) res.got = Object.keys(c.expect).reduce(function (o, k) { o[k] = r[k]; return o; }, {});
      if (typeof checks !== 'undefined') res.checks = checks.map(function (ck) {
        try { return { label: ck.label, ok: !!ck.test(c.state, r) }; } catch (e) { return { label: ck.label, ok: false, error: String(e.message || e) }; }
      });
      if (typeof render === 'function') {
        __rec.calls = []; __rec.binds = []; __rec.problems = [];
        try { render(clone(c.state), r, __kit); } catch (e) { res.renderError = String(e && e.message || e); }
        res.calls = __rec.calls; res.binds = __rec.binds; res.problems = __rec.problems;
      } else res.renderError = 'render() is not defined';
    } catch (e) { res.error = String(e && e.message || e); }
    return res;
  });
})(__CASES__);
var __out_json = JSON.stringify(__out);
"""


def js_engine() -> str | None:
    """'quickjs' (pinned dependency, used in assessment), 'node' (local fallback) or None."""
    try:
        import quickjs  # type: ignore  # noqa: F401
        return "quickjs"
    except ImportError:
        return "node" if shutil.which("node") else None


def _run_js(source: str) -> str:
    try:
        import quickjs  # type: ignore
        ctx = quickjs.Context()
        ctx.set_time_limit(3)
        ctx.set_memory_limit(64 * 1024 * 1024)
        return ctx.eval(source + "\n__out_json;")
    except ImportError:
        node = shutil.which("node")
        if not node:
            raise RuntimeError("no JavaScript engine: install quickjs (pip) or node")
        proc = subprocess.run([node, "-e", source + "\n;process.stdout.write(__out_json);"], capture_output=True, text=True, timeout=15)
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


def _check_bind(b: dict, ctl_type: dict[str, str]) -> str | None:
    fn, bind = b["fn"], b["bind"]
    if isinstance(bind, str):
        if bind not in ctl_type:
            return f"{fn} is bound to unknown control '{bind}'"
        want = BIND_TYPES.get(fn)
        if want and ctl_type[bind] not in want:
            return f"{fn} is bound to '{bind}' ({ctl_type[bind]}); needs one of {sorted(want)}"
    elif isinstance(bind, list):
        for x in bind:
            if x not in ctl_type:
                return f"{fn} is bound to unknown control '{x}'"
    elif isinstance(bind, dict):
        if ctl_type.get(str(bind.get("id"))) != "matrix":
            return f"{fn} binds a row of '{bind.get('id')}', which is not a matrix control"
    return None


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

    # 1. structure ------------------------------------------------------------------------------
    ctl_type = {str(c.get("id")): str(c.get("type", "slider")).lower() for c in controls}
    if len(controls) < 2:
        fails.append("fewer than 2 controls")
    scenes = [str(s.get("id")) for s in content.get("scenes", [])] or ["s1"]
    for c in controls:
        if ctl_type[str(c.get("id"))] not in CTL_TYPES:
            fails.append(f"control {c.get('id')}: unknown type {c.get('type')}")
        if c.get("scene") is not None and str(c["scene"]) not in scenes:
            fails.append(f"control {c.get('id')}: scene '{c['scene']}' does not exist")
    exps = content.get("explorations", [])
    if len(exps) < 2:
        fails.append("fewer than 2 explorations")
    for i, ex in enumerate(exps):
        for k in ex.get("preset", {}):
            if k not in ctl_type:
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
    for fn in sorted(set(re.findall(r"\bkit\.([A-Za-z_]\w*)", parts["render"])) - KIT_FUNCS):
        fails.append(f"render uses unknown kit.{fn}")
    if not fails:
        passed.append("structure")

    # 2 + 3. run compute, checks and render on every state ---------------------------------------
    base = _defaults(controls)
    cases = [{"name": "defaults", "state": base}]
    for i, ex in enumerate(exps):
        cases.append({"name": f"exploration {i + 1}", "state": {**base, **ex.get("preset", {})}})
    for i, t in enumerate(tests):
        cases.append({"name": f"test {i + 1}", "state": {**base, **t.get("state", {})}, "expect": t.get("expect", {}), "tol": t.get("tol", 1e-6)})
    if js_engine() is None:   # an environment problem, not a defect of the reply: do not trigger repairs
        passed.append("runtime checks skipped: no JavaScript engine available")
        return {"ok": not fails, "failures": fails, "passed": passed}
    src = "\n".join([(HERE / "mathlib.js").read_text(encoding="utf-8"), parts["compute"], parts["render"], parts.get("checks", ""),
                     HARNESS.replace("__CASES__", json.dumps(cases))])
    try:
        results = json.loads(_run_js(src))
    except Exception as e:  # syntax errors, timeouts, engine failures
        fails.append(f"generated code could not run: {e}")
        return {"ok": False, "failures": fails, "passed": passed}

    seen = set()
    def once(msg):
        key = re.sub(r"^[^:]+: ", "", msg)
        if key not in seen:
            seen.add(key)
            fails.append(msg)

    drawn = set()
    for case, res in zip(cases, results):
        name = res["name"]
        if res.get("error"):
            fails.append(f"{name}: compute threw: {res['error']}")
            continue
        if res.get("nonfinite"):
            once(f"{name}: compute returned a non-finite number at {res['nonfinite']}")
        for ck in res.get("checks", []):
            if not ck["ok"]:
                fails.append(f"{name}: live check failed: {ck['label']}" + (f" ({ck['error']})" if ck.get("error") else ""))
        for k, want in case.get("expect", {}).items():
            got = res.get("got", {}).get(k)
            if _close(got, want, case.get("tol", 1e-6)):
                passed.append(f"{name}: {k}")
            else:
                fails.append(f"{name}: expected {k} = {json.dumps(want)}, got {json.dumps(got)}")
        if res.get("renderError"):
            once(f"{name}: render threw: {res['renderError']}")
        for p in res.get("problems", []):
            once(f"{name}: {p}")
        for call in res.get("calls", []):
            drawn.add(call["target"])
            if call["target"] not in scenes:
                once(f"{name}: kit.{call['fn']} draws into '#{call['target']}', which is not a scene id")
        for b in res.get("binds", []):
            msg = _check_bind(b, ctl_type)
            if msg:
                once(f"{name}: {msg}")
    if results and not results[0].get("error") and not results[0].get("renderError"):
        for sc in scenes:
            if sc not in drawn:
                fails.append(f"scene '{sc}' has no visual (render never draws into '#{sc}')")
        if not any(f.startswith(("defaults", "exploration", "test", "scene")) for f in fails):
            passed.append("render on all states")
    return {"ok": not fails, "failures": fails, "passed": passed}


if __name__ == "__main__":
    report = validate(Path(sys.argv[1]).read_text(encoding="utf-8"))
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    sys.exit(0 if report["ok"] else 1)
