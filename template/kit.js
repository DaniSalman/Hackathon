/* kit.js — Paper -> Playground visual kit (3Blue1Brown-inspired).
   Generic, paper-agnostic components. The model writes compute(s) and render(s, r, kit);
   render() calls the components below. All styling, motion, linking and controls live here. */
(function () {
  'use strict';

  // ------------------------------------------------------------------ palette & state
  var PALETTE = {
    blue: '#58C4DD', teal: '#5CD0B3', green: '#83C167', yellow: '#FFE45E', gold: '#F0AC5F', orange: '#FF862F',
    red: '#FC6255', maroon: '#C55F73', purple: '#B189D4', pink: '#E06BC5', grey: '#9DA3AD', gray: '#9DA3AD', white: '#ECECEC'
  };
  var SERIES = ['blue', 'yellow', 'green', 'red', 'purple', 'teal', 'gold', 'pink'];
  var GREEK = { alpha: 'α', beta: 'β', gamma: 'γ', delta: 'δ', epsilon: 'ε', eps: 'ε', zeta: 'ζ', eta: 'η', theta: 'θ', kappa: 'κ', lambda: 'λ',
    mu: 'μ', nu: 'ν', xi: 'ξ', pi: 'π', rho: 'ρ', sigma: 'σ', tau: 'τ', phi: 'φ', chi: 'χ', psi: 'ψ', omega: 'ω',
    Gamma: 'Γ', Delta: 'Δ', Theta: 'Θ', Lambda: 'Λ', Pi: 'Π', Sigma: 'Σ', Phi: 'Φ', Psi: 'Ψ', Omega: 'Ω' };
  var NS = 'http://www.w3.org/2000/svg';
  var REDUCED = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  var fmt = M.fmt;

  var SYM = {};        // symbol key -> {color, meaning}
  var CTL = {};        // control id -> normalized spec
  var CTLDOM = {};     // control id -> container element
  var state = {};      // live control values
  var DEFAULTS = {};
  var DATA = {}, computeFn = null, renderFn = null, CHECKS = [];
  var result = null;
  var FAST = false;    // dragging / scripted animation: skip long easing and pulses
  var DRAG = false;
  var ERRORS = [];

  // ------------------------------------------------------------------ helpers
  var isNum = function (v) { return typeof v === 'number' && isFinite(v); };
  var clamp = function (x, a, b) { return Math.min(b, Math.max(a, x)); };
  var asArray = function (v) { return Array.isArray(v) ? v : v == null ? [] : [v]; };
  var clone = function (v) { return v == null ? v : JSON.parse(JSON.stringify(v)); };
  function $(q, root) { return (root || document).querySelector(q); }
  function el(tag, cls, parent, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    if (parent) parent.appendChild(e);
    return e;
  }
  function svg(tag, attrs, parent) {
    var e = document.createElementNS(NS, tag);
    if (attrs) for (var k in attrs) if (attrs[k] != null) {
      if (k === 'fill' && tag === 'text') e.style.fill = attrs[k]; else e.setAttribute(k, attrs[k]);
    }
    if (parent) parent.appendChild(e);
    return e;
  }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; });
  }
  function setHTML(node, html) { if (node._h === html) return false; var first = node._h === undefined; node._h = html; node.innerHTML = html; return !first; }
  function decimalsOf(step) { var s = String(step); if (s.indexOf('e-') > 0) return +s.split('e-')[1]; return (s.split('.')[1] || '').length; }
  function niceStep(span) { var r = span / 100, p = Math.pow(10, Math.floor(Math.log10(r || 1))), m = r / p; return (m >= 5 ? 5 : m >= 2 ? 2 : 1) * p; }
  function ease(t) { return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  // ------------------------------------------------------------------ colors
  function col(c, fb) {
    if (c && PALETTE[c]) return PALETTE[c];
    if (c && SYM[c]) return SYM[c].color;
    if (c && typeof c === 'string') { var k = symKey(c); if (k) return SYM[k].color; }
    if (c && /^#[0-9a-f]{3}([0-9a-f]{3})?$/i.test(c)) return c;
    return fb || PALETTE.blue;
  }
  function compColor(o) { return col(o.color || o.sym, PALETTE.blue); }
  function rgb(h) {
    h = h.replace('#', ''); if (h.length === 3) h = h.split('').map(function (x) { return x + x; }).join('');
    var n = parseInt(h, 16); return [n >> 16 & 255, n >> 8 & 255, n & 255];
  }
  function mix(a, b, t) {
    var A = rgb(a), B = rgb(b); t = clamp(t, 0, 1);
    return 'rgb(' + A.map(function (v, i) { return Math.round(v + (B[i] - v) * t); }).join(',') + ')';
  }
  function lumOf(rgbStr) { var m = rgbStr.match(/\d+/g).map(Number); return (0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2]) / 255; }

  // ------------------------------------------------------------------ symbol mini-markup  {p_i}  {d_k}  {W^Q}  {alpha}
  var SYM_SRC = '\\{([A-Za-z\\u0370-\\u03FF][A-Za-z0-9\\u0370-\\u03FF]*(?:_[A-Za-z0-9\\u0370-\\u03FF,+\\-]+)?(?:\\^[A-Za-z0-9\\u0370-\\u03FF+\\-*′]+)?)\\}';
  function symRe() { return new RegExp(SYM_SRC, 'g'); }
  function parseSym(k) {
    var m = k.match(/^([^_^]+)(?:_([^^]+))?(?:\^(.+))?$/);
    if (!m) return { base: k, sub: '', sup: '' };
    return { base: GREEK[m[1]] || m[1], sub: m[2] ? (GREEK[m[2]] || m[2]) : '', sup: m[3] ? (GREEK[m[3]] || m[3]) : '' };
  }
  function symKey(k) {
    if (!k) return null;
    if (SYM[k]) return k;
    var base = k.split(/[_^]/)[0];
    if (SYM[base]) return base;
    var c = [base + '_i', base + '_j', base + '_k', base + '_t', base + '_n'];
    for (var i = 0; i < c.length; i++) if (SYM[c[i]]) return c[i];
    // row/element notation: {q_1} borrows the colour of matrix Q, {v_j} of V
    var alt = base === base.toLowerCase() ? base.toUpperCase() : base.toLowerCase();
    if (alt !== base && SYM[alt]) return alt;
    return null;
  }
  function symColor(k) { var s = symKey(k); return s ? SYM[s].color : PALETTE.white; }
  function symHTML(k) {
    var p = parseSym(k), sk = symKey(k), c = sk ? SYM[sk].color : 'var(--ink)';
    return '<span class="sym" data-sym="' + esc(sk || k) + '" style="--c:' + c + '">' + esc(p.base) +
      (p.sub ? '<sub>' + esc(p.sub) + '</sub>' : '') + (p.sup ? '<sup>' + esc(p.sup) + '</sup>' : '') + '</span>';
  }
  function md(t) {
    if (t == null) return '';
    var h = esc(String(t));
    h = h.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
    h = h.replace(symRe(), function (_, k) { return symHTML(k); });
    return h.replace(/\n/g, '<br>');
  }
  function plain(t) { return String(t == null ? '' : t).replace(symRe(), function (_, k) { var p = parseSym(k); return p.base + (p.sub ? '_' + p.sub : '') + (p.sup ? '^' + p.sup : ''); }).replace(/\*\*/g, ''); }
  /* SVG text with colored symbol tspans. */
  function stext(t, text) {
    text = text == null ? '' : String(text);
    if (t._txt === text) return; t._txt = text;
    t.textContent = '';
    var re = symRe(), last = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > last) t.appendChild(document.createTextNode(text.slice(last, m.index)));
      var p = parseSym(m[1]), c = symColor(m[1]);
      svg('tspan', { fill: c, class: 'msym' }, t).textContent = p.base;
      if (p.sub) svg('tspan', { fill: c, 'baseline-shift': 'sub', 'font-size': '72%' }, t).textContent = p.sub;
      if (p.sup) svg('tspan', { fill: c, 'baseline-shift': 'super', 'font-size': '72%' }, t).textContent = p.sup;
      last = re.lastIndex;
    }
    if (last < text.length) t.appendChild(document.createTextNode(text.slice(last)));
  }

  // ------------------------------------------------------------------ tween engine (Manim-like "smooth")
  var active = new Set(), raf = 0;
  function lerp(a, b, e) {
    if (Array.isArray(b)) return b.map(function (bv, i) { return a[i] + (bv - a[i]) * e; });
    return a + (b - a) * e;
  }
  function pathD(p) {
    var d = '', pen = false;
    for (var i = 0; i + 1 < p.length; i += 2) {
      var x = p[i], y = p[i + 1];
      if (!isNum(x) || !isNum(y)) { pen = false; continue; }
      d += (pen ? 'L' : 'M') + x.toFixed(2) + ',' + y.toFixed(2); pen = true;
    }
    return d || 'M0,0';
  }
  function applyVals(node, vals) {
    if (node._apply) { node._apply(vals); return; }
    for (var k in vals) {
      var v = vals[k];
      if (k === 'pts') node.setAttribute('d', pathD(v) + (node._closed ? 'Z' : ''));
      else if (k === 'heat') node._heat(v);
      else node.setAttribute(k, (k === 'height' || k === 'width' || k === 'r') && v < 0 ? 0 : v);
    }
  }
  function tween(node, to, opt) {
    opt = opt || {};
    var ms = REDUCED ? 0 : opt.ms != null ? opt.ms : FAST ? 60 : 420;
    var cur = node._cur || (node._cur = {}), st = {};
    for (var k in to) {
      var v = to[k], a = cur[k];
      if (a === undefined) a = opt.from && opt.from[k] !== undefined ? opt.from[k] : v;
      if (Array.isArray(v) && (!Array.isArray(a) || a.length !== v.length)) a = v;
      if (!Array.isArray(v) && !isNum(a)) a = v;
      st[k] = a;
    }
    if (ms <= 0) { active.delete(node); Object.assign(cur, to); applyVals(node, Object.assign({}, cur)); return; }
    node._tw = { st: st, to: to, t0: performance.now(), ms: ms };
    active.add(node);
    if (!raf) raf = requestAnimationFrame(stepTweens);
  }
  function stepTweens(now) {
    active.forEach(function (node) {
      var tw = node._tw, t = Math.min(1, (now - tw.t0) / tw.ms), e = ease(t), vals = {};
      for (var k in tw.to) vals[k] = lerp(tw.st[k], tw.to[k], e);
      Object.assign(node._cur, vals);
      applyVals(node, Object.assign({}, node._cur));
      if (t >= 1) active.delete(node);
    });
    raf = active.size ? requestAnimationFrame(stepTweens) : 0;
  }
  function pulse(node) {
    if (REDUCED || FAST || !node) return;
    node.classList.remove('pulse'); void node.getBoundingClientRect(); node.classList.add('pulse');
  }
  function changed(node, v) {
    var prev = node._val; node._val = v;
    if (prev === undefined) return false;
    if (isNum(prev) && isNum(v)) return Math.abs(prev - v) > 1e-9 * Math.max(1, Math.abs(v));
    return prev !== v;
  }

  // ------------------------------------------------------------------ tooltip & linked highlighting
  var tipEl = null;
  function showTip(html, e) { if (!tipEl || !html) return hideTip(); tipEl.innerHTML = html; tipEl.classList.add('on'); moveTip(e); }
  function moveTip(e) {
    if (!tipEl || !e) return;
    var pad = 14, x = e.clientX + pad, y = e.clientY + pad, r = tipEl.getBoundingClientRect();
    if (x + r.width > innerWidth - 8) x = e.clientX - r.width - pad;
    if (y + r.height > innerHeight - 8) y = e.clientY - r.height - pad;
    tipEl.style.transform = 'translate(' + Math.max(4, x) + 'px,' + Math.max(4, y) + 'px)';
  }
  function hideTip() { if (tipEl) tipEl.classList.remove('on'); }
  function hover(node, tipFn, axesFn) {
    node._tipFn = tipFn; node._hoverAxes = axesFn;
    if (node._wired) return; node._wired = true;
    node.addEventListener('pointerenter', function (e) {
      if (DRAG) return;
      if (node._hoverAxes) setActive(node._hoverAxes());
      if (node._tipFn) showTip(node._tipFn(), e);
    });
    node.addEventListener('pointermove', function (e) { if (!DRAG) moveTip(e); });
    node.addEventListener('pointerleave', function () { if (node._hoverAxes) setActive(null); hideTip(); });
  }
  var ACTIVE = null;
  function link(node, axes) { node._axes = axes; node.classList.add('lk'); }
  function setActive(a) { ACTIVE = a && Object.keys(a).length ? a : null; applyLinks(); }
  function matchAxes(ax) {
    var shared = 0, ok = true;
    for (var k in ax) if (k in ACTIVE) { shared++; if (ax[k] !== ACTIVE[k]) ok = false; }
    return shared ? (ok ? 1 : -1) : 0;
  }
  function applyLinks() {
    document.querySelectorAll('.lk').forEach(function (n) {
      var st = 0;
      if (ACTIVE && n._axes) {
        var alts = Array.isArray(n._axes) ? n._axes : [n._axes];
        for (var i = 0; i < alts.length; i++) { var r = matchAxes(alts[i]); if (r === 1) { st = 1; break; } if (r === -1) st = -1; }
      }
      n.classList.toggle('hl', st === 1); n.classList.toggle('dim', st === -1);
    });
  }
  function symHighlight(key, on) {
    if (!key) return;
    document.querySelectorAll('[data-sym="' + key.replace(/"/g, '') + '"]').forEach(function (n) { n.classList.toggle('symhl', on); });
  }

  // ------------------------------------------------------------------ pointer dragging
  function svgPt(svgEl, e) {
    var r = svgEl.getBoundingClientRect(), vb = svgEl.viewBox.baseVal;
    return [(e.clientX - r.left) * vb.width / r.width, (e.clientY - r.top) * vb.height / r.height];
  }
  function dragger(target, onMove) {
    target.addEventListener('pointerdown', function (e) {
      if (e.button !== 0) return;
      if (onMove(e, true) === false) return;
      e.preventDefault(); e.stopPropagation();
      try { target.setPointerCapture(e.pointerId); } catch (_) { /* ignore */ }
      DRAG = true; FAST = true; hideTip(); document.body.classList.add('dragging');
      var mv = function (ev) { onMove(ev, false); };
      var up = function () {
        target.removeEventListener('pointermove', mv); target.removeEventListener('pointerup', up); target.removeEventListener('pointercancel', up);
        DRAG = false; FAST = false; document.body.classList.remove('dragging'); scheduleUpdate();
      };
      target.addEventListener('pointermove', mv); target.addEventListener('pointerup', up); target.addEventListener('pointercancel', up);
    });
  }

  // ------------------------------------------------------------------ slots: each kit call owns a <figure> inside its target
  var slotUse = new Map();
  var FILL = { bars: 1, plot: 1, plane: 0, graph: 1, svg: 1, steps: 1, formula: 1, note: 1 };
  function hostOf(sel) {
    var node = null;
    if (sel && sel.nodeType === 1) node = sel;
    else if (typeof sel === 'string') {
      var id = sel.replace(/^#/, '');
      node = document.getElementById('viz-' + id) || document.getElementById(id);
      if (node && !node.classList.contains('viz')) node = node.querySelector('.viz') || node;
    }
    if (!node) { node = document.querySelector('.scene .viz'); if (node) note('render', 'unknown target "' + sel + '" — drawn in the first scene instead'); }
    return node;
  }
  function slot(sel, kind, o) {
    var host = hostOf(sel); if (!host) return null;
    var n = slotUse.get(host) || 0; slotUse.set(host, n + 1);
    var fig = host.children[n];
    if (!fig || fig.dataset.kind !== kind) {
      var nf = el('figure', 'comp comp-' + kind); nf.dataset.kind = kind; nf._st = {};
      if (fig) host.replaceChild(nf, fig); else host.appendChild(nf);
      fig = nf;
    }
    var w = o && o.width;
    fig.style.flex = w ? (w <= 1 ? '0 0 calc(' + (w * 100) + '% - var(--gap) * ' + (1 - w).toFixed(4) + ')' : '0 0 ' + w + 'px') : '';
    fig.classList.toggle('fill', !w && !!FILL[kind]);
    if (o && o.sym) fig.dataset.sym = symKey(o.sym) || o.sym; else delete fig.dataset.sym;
    return fig;
  }
  function pruneSlots() {
    document.querySelectorAll('.viz').forEach(function (host) {
      var n = slotUse.get(host) || 0;
      while (host.children.length > n) host.removeChild(host.lastChild);
    });
    slotUse.clear();
  }
  function innerW(fig) {
    var cs = getComputedStyle(fig);
    return Math.max(220, Math.floor(fig.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)));
  }
  function availW(fig) {
    var host = fig.parentNode, w = host ? host.clientWidth : 600;
    return Math.max(220, Math.floor(w - 26));
  }
  function caption(fig, title, hint, legend) {
    var cap = fig._cap;
    if (!cap) { cap = fig._cap = el('figcaption'); fig.insertBefore(cap, fig.firstChild); }
    var key = (title || '') + '|' + (hint || '') + '|' + (legend || '');
    if (cap._k === key) return; cap._k = key;
    cap.innerHTML = (title ? '<span class="ct">' + md(title) + '</span>' : '') + (hint ? '<span class="hint">' + esc(hint) + '</span>' : '') + (legend || '');
    cap.style.display = title || hint || legend ? '' : 'none';
  }
  function frame(fig, W, H, label) {
    var s = fig._st;
    if (!s.svg || s.W !== W || s.H !== H) {
      if (s.svg) s.svg.remove();
      s.svg = svg('svg', { class: 'cv', viewBox: '0 0 ' + W + ' ' + H, width: W, height: H, role: 'img' });
      fig.appendChild(s.svg);
      s.W = W; s.H = H; s.layers = {}; s.wired = {}; s.gridDone = false; s.clip = false;
    }
    if (label) s.svg.setAttribute('aria-label', plain(label));
    return s;
  }
  function layer(s, name) { return s.layers[name] || (s.layers[name] = svg('g', { class: 'ly-' + name }, s.svg)); }
  function pool(parent, n, make) {
    var arr = parent._pool || (parent._pool = []);
    while (arr.length < n) { var e = make(arr.length); e._new = true; parent.appendChild(e); arr.push(e); }
    while (arr.length > n) arr.pop().remove();
    return arr;
  }

  // ------------------------------------------------------------------ scales & axes
  function lin(d0, d1, r0, r1) {
    var k = d1 === d0 ? 0 : (r1 - r0) / (d1 - d0);
    var f = function (v) { return r0 + (v - d0) * k; };
    f.inv = function (p) { return k === 0 ? d0 : d0 + (p - r0) / k; };
    f.d0 = d0; f.d1 = d1; return f;
  }
  function niceTicks(a, b, n) {
    n = n || 5; if (a === b) { a -= 1; b += 1; }
    var span = b - a, step0 = Math.pow(10, Math.floor(Math.log10(span / n))), err = span / n / step0;
    var step = step0 * (err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1), t = [];
    for (var v = Math.ceil(a / step - 1e-9) * step; v <= b + step * 1e-9; v += step) t.push(+v.toFixed(12));
    return t;
  }
  function fmtTick(v) { return String(+v.toPrecision(8)); }
  function autoRange(vals, includeZero) {
    var f = vals.filter(isNum);
    if (!f.length) return [0, 1];
    var lo = Math.min.apply(null, f), hi = Math.max.apply(null, f);
    if (includeZero !== false) { if (lo > 0 && lo < 0.35 * hi) lo = 0; if (hi < 0 && hi > 0.35 * lo) hi = 0; }
    if (hi - lo < 1e-12) { if (lo >= 0) { lo = 0; hi = hi > 0 ? hi * 1.25 : 1; } else { hi = 0; lo *= 1.25; } }
    var t = niceTicks(lo, hi, 5); return [Math.min(lo, t[0]), Math.max(hi, t[t.length - 1])];
  }
  function drawAxes(s, x, y, box, o) {
    var g = layer(s, 'axes'); g.textContent = '';
    if (y) niceTicks(y.d0, y.d1, o.yTicks || 5).forEach(function (v) {
      var py = y(v); if (py < box.t - 1 || py > box.b + 1) return;
      svg('line', { x1: box.l, x2: box.r, y1: py, y2: py, class: Math.abs(v) < 1e-12 ? 'axis0' : 'grid' }, g);
      svg('text', { x: box.l - 7, y: py + 4, 'text-anchor': 'end', class: 'tick' }, g).textContent = fmtTick(v);
    });
    if (x) niceTicks(x.d0, x.d1, o.xTicks || 6).forEach(function (v) {
      var px = x(v); if (px < box.l - 1 || px > box.r + 1) return;
      svg('line', { x1: px, x2: px, y1: box.t, y2: box.b, class: Math.abs(v) < 1e-12 ? 'axis0' : 'grid' }, g);
      svg('text', { x: px, y: box.b + 16, 'text-anchor': 'middle', class: 'tick' }, g).textContent = fmtTick(v);
    });
    svg('line', { x1: box.l, x2: box.r, y1: box.b, y2: box.b, class: 'axis' }, g);
    svg('line', { x1: box.l, x2: box.l, y1: box.t, y2: box.b, class: 'axis' }, g);
    if (o.xLabel) stext(svg('text', { x: (box.l + box.r) / 2, y: box.b + 34, 'text-anchor': 'middle', class: 'axl' }, g), o.xLabel);
    if (o.yLabel) stext(svg('text', { x: -(box.t + box.b) / 2, y: 13, 'text-anchor': 'middle', class: 'axl', transform: 'rotate(-90)' }, g), o.yLabel);
  }
  function labelAt(labels, i, fallback) {
    if (typeof labels === 'function') return labels(i);
    if (Array.isArray(labels) && labels[i] != null) return String(labels[i]);
    return fallback;
  }

  // ------------------------------------------------------------------ arrows (shared by plane / svg)
  function arrowNode(parent, cls) {
    var g = svg('g', { class: cls || 'arrow' }, parent);
    var line = svg('line', { 'stroke-linecap': 'round' }, g);
    var head = svg('polygon', {}, g);
    g._apply = function (vals) {
      var v = vals.vec, x1 = v[0], y1 = v[1], x2 = v[2], y2 = v[3];
      var dx = x2 - x1, dy = y2 - y1, L = Math.hypot(dx, dy) || 1e-9, ux = dx / L, uy = dy / L;
      var hl = Math.min(g._hl || 13, L * 0.6), hw = hl * 0.48;
      var bx = x2 - ux * hl, by = y2 - uy * hl;
      line.setAttribute('x1', x1); line.setAttribute('y1', y1); line.setAttribute('x2', bx + ux * 1); line.setAttribute('y2', by + uy * 1);
      head.setAttribute('points', x2 + ',' + y2 + ' ' + (bx - uy * hw) + ',' + (by + ux * hw) + ' ' + (bx + uy * hw) + ',' + (by - ux * hw));
      if (g._after) g._after(x2, y2, ux, uy);
    };
    g._style = function (c, w, dashed, op) {
      line.setAttribute('stroke', c); line.setAttribute('stroke-width', w || 3); line.setAttribute('stroke-dasharray', dashed ? '6 5' : '');
      head.setAttribute('fill', c); g.setAttribute('opacity', op == null ? 1 : op); g._hl = 9 + (w || 3) * 1.6;
    };
    return g;
  }

  // ================================================================== COMPONENTS
  var kit = {};

  /* bars(target, values, {labels, sym|color, colors, title, min, max, decimals, bind, axis, ref, highlight, unit, xLabel, yLabel, height, width, tip}) */
  kit.bars = function (sel, values, o) {
    o = o || {};
    var fig = slot(sel, 'bars', o); if (!fig) return;
    var ctl = o.bind && CTL[o.bind] ? CTL[o.bind] : null;
    var vals = asArray(ctl ? state[o.bind] : values).map(Number), n = vals.length;
    caption(fig, o.title, ctl ? '↕ drag the bars' : '');
    var W = innerW(fig), H = o.height || 220, s = frame(fig, W, H, o.title || 'bar chart');
    var fin = vals.filter(isNum);
    var refs = asArray(o.ref).map(function (r) { return typeof r === 'number' ? { y: r } : r; }).filter(function (r) { return r && isNum(r.y); });
    var lo, hi;
    if (ctl && ctl.type === 'simplex') { lo = 0; hi = o.max != null ? o.max : 1; }
    else if (ctl) { lo = o.min != null ? o.min : ctl.min; hi = o.max != null ? o.max : ctl.max; }
    else {
      var rr = autoRange(fin.concat([0], refs.map(function (r) { return r.y; })), true);
      lo = o.min != null ? o.min : rr[0]; hi = o.max != null ? o.max : rr[1];
    }
    if (!(hi > lo)) hi = lo + 1;
    var box = { l: 46, r: W - 8, t: 24, b: H - (o.xLabel ? 46 : 28) };
    var y = lin(lo, hi, box.b, box.t);
    drawAxes(s, null, y, box, { yTicks: 4, xLabel: o.xLabel, yLabel: o.yLabel });
    var bw = (box.r - box.l) / Math.max(n, 1), base = y(clamp(0, lo, hi));
    var c0 = compColor(o);
    var gr = layer(s, 'ref'), gb = layer(s, 'bars'), gv = layer(s, 'vals'), gl = layer(s, 'labs'), gh = layer(s, 'handles');
    gr.textContent = '';
    refs.forEach(function (r) {
      var c = col(r.color || r.sym, PALETTE.white), py = y(r.y);
      svg('line', { x1: box.l, x2: box.r, y1: py, y2: py, class: 'ref', stroke: c }, gr);
      if (r.label) stext(svg('text', { x: box.r - 4, y: py - 5, 'text-anchor': 'end', class: 'reftxt', fill: c }, gr), r.label);
    });
    var hl = asArray(o.highlight);
    var rects = pool(gb, n, function () { return svg('rect', { rx: 3 }); });
    var vt = pool(gv, n, function () { return svg('text', { class: 'val', 'text-anchor': 'middle' }); });
    var lt = pool(gl, n, function () { return svg('text', { class: 'lab', 'text-anchor': 'middle' }); });
    var hd = pool(gh, ctl ? n : 0, function () { return svg('circle', { r: 5.5, class: 'handle' }); });
    for (var i = 0; i < n; i++) {
      var v = vals[i], ok = isNum(v), yv = ok ? y(clamp(v, lo, hi)) : base;
      var top = Math.min(yv, base), h = Math.max(Math.abs(base - yv), ok && v !== 0 ? 1 : 0);
      var x = box.l + i * bw + bw * 0.16, w = bw * 0.68;
      var c = o.colors ? col(o.colors[i % o.colors.length], c0) : c0;
      var r = rects[i];
      r.setAttribute('fill', c); r.setAttribute('fill-opacity', 0.78); r.setAttribute('stroke', c); r.setAttribute('stroke-width', 1.2);
      r.classList.toggle('mark', hl.indexOf(i) >= 0);
      tween(r, { x: x, y: top, width: w, height: h }, { from: r._new ? { y: base, height: 0 } : null });
      var label = labelAt(o.labels, i, String(i + 1));
      var t = vt[i]; stext(t, ok ? fmt(v, o.decimals) + (o.unit ? ' ' + o.unit : '') : '—');
      var vy = ok && v < 0 ? top + h + 15 : top - (ctl ? 13 : 6);
      tween(t, { x: x + w / 2, y: vy }, { from: t._new ? { y: base - 6 } : null });
      var lb = lt[i]; stext(lb, label); lb.setAttribute('x', x + w / 2); lb.setAttribute('y', box.b + 17);
      if (ctl) { var hh = hd[i]; hh.setAttribute('stroke', c); tween(hh, { cx: x + w / 2, cy: yv }, { from: hh._new ? { cy: base } : null }); hh._new = false; }
      if (o.axis) { link(r, (function (ii) { var a = {}; a[o.axis] = ii; return a; })(i)); link(lb, r._axes); }
      (function (ii, lab, node) {
        hover(node, function () {
          var vv = (ctl ? state[o.bind] : vals)[ii];
          return md(lab) + ': <span class="tv">' + fmt(vv, 4) + '</span>' + (o.tip ? '<div class="tm">' + md(o.tip(ii, vv)) + '</div>' : '');
        }, o.axis ? function () { var a = {}; a[o.axis] = ii; return a; } : null);
      })(i, label, r);
      if (changed(r, v)) pulse(r);
      r._new = false; t._new = false;
    }
    s.y = y; s.box = box; s.bw = bw; s.n = n; s.bind = o.bind;
    if (ctl && !s.wired.drag) {
      s.wired.drag = true; s.svg.classList.add('draggable');
      dragger(s.svg, function (e, start) {
        var p = svgPt(s.svg, e);
        if (start) {
          var i0 = Math.floor((p[0] - s.box.l) / s.bw);
          if (p[0] < s.box.l || i0 < 0 || i0 >= s.n) return false;
          s.dragI = i0;
        }
        setItem(s.bind, s.dragI, s.y.inv(p[1]));
      });
    }
  };

  /* matrix(target, A, {rowLabels, colLabels, sym|color, title, decimals, min, max, diverging, bind, axes:[rowAxis,colAxis], hover:'cell'|'row'|'col', highlight:{rows,cols,cells}, tip(i,j,v)}) */
  kit.matrix = function (sel, A, o) {
    o = o || {};
    var fig = slot(sel, 'matrix', o); if (!fig) return;
    var ctl = o.bind && CTL[o.bind] ? CTL[o.bind] : null;
    A = ctl ? state[o.bind] : A;
    A = asArray(A).map(function (r) { return asArray(r).map(Number); });
    var R = A.length, C = R ? A[0].length : 0, dec = o.decimals != null ? o.decimals : 2;
    caption(fig, o.title, ctl ? '↕ drag a cell · double-click to type' : '');
    var maxLen = 3;
    A.forEach(function (r) { r.forEach(function (v) { maxLen = Math.max(maxLen, fmt(v, dec).length); }); });
    var cs = o.cell || Math.max(42, Math.min(64, 14 + maxLen * 8.2));
    var rl = o.rowLabels, cl = o.colLabels;
    var rlw = 0; if (rl) for (var a = 0; a < R; a++) rlw = Math.max(rlw, plain(labelAt(rl, a, '')).length);
    var padL = rl ? Math.max(28, rlw * 8 + 18) : 12, padT = cl ? 24 : 8;
    var W = Math.round(padL + C * cs + 14), H = Math.round(padT + R * cs + 8);
    var s = frame(fig, W, H, o.title || 'matrix');
    var flat = []; A.forEach(function (r) { r.forEach(function (v) { if (isNum(v)) flat.push(v); }); });
    var lo = o.min != null ? o.min : (flat.length ? Math.min.apply(null, flat) : 0);
    var hi = o.max != null ? o.max : (flat.length ? Math.max.apply(null, flat) : 1);
    var div = o.diverging != null ? o.diverging : lo < 0;
    var mabs = Math.max(Math.abs(lo), Math.abs(hi)) || 1;
    var c = compColor(o), cneg = col(o.negColor, PALETTE.red), BG = '#1a1d23';
    var heatT = function (v) {
      if (!isNum(v)) return 0;
      if (div) return clamp(v / mabs, -1, 1);
      return hi > lo ? clamp((v - lo) / (hi - lo), 0, 1) : 0.5;
    };
    var fillOf = function (t) { return t >= 0 ? mix(BG, c, 0.08 + 0.82 * t) : mix(BG, cneg, 0.08 + 0.82 * -t); };
    var gb = layer(s, 'brackets'); gb.textContent = '';
    var x0 = padL, y0 = padT, x1 = padL + C * cs, y1 = padT + R * cs;
    svg('path', { class: 'bracket', stroke: c, d: 'M' + (x0 + 3) + ',' + (y0 - 3) + 'H' + (x0 - 4) + 'V' + (y1 + 3) + 'H' + (x0 + 3) }, gb);
    svg('path', { class: 'bracket', stroke: c, d: 'M' + (x1 - 3) + ',' + (y0 - 3) + 'H' + (x1 + 4) + 'V' + (y1 + 3) + 'H' + (x1 - 3) }, gb);
    var gl = layer(s, 'labels'), gc = layer(s, 'cells');
    var ax = o.axes || [];
    var rlt = pool(gl, (rl ? R : 0) + (cl ? C : 0), function () { return svg('text', { class: 'lab' }); });
    var k = 0;
    if (rl) for (var i = 0; i < R; i++, k++) {
      var t = rlt[k]; stext(t, labelAt(rl, i, '')); t.setAttribute('x', padL - 10); t.setAttribute('y', padT + i * cs + cs / 2 + 4); t.setAttribute('text-anchor', 'end');
      if (ax[0]) { var ra = {}; ra[ax[0]] = i; link(t, ra); hover(t, null, (function (aa) { return function () { return aa; }; })(ra)); }
    }
    if (cl) for (var j = 0; j < C; j++, k++) {
      var t2 = rlt[k]; stext(t2, labelAt(cl, j, '')); t2.setAttribute('x', padL + j * cs + cs / 2); t2.setAttribute('y', padT - 8); t2.setAttribute('text-anchor', 'middle');
      if (ax[1]) { var ca = {}; ca[ax[1]] = j; link(t2, ca); hover(t2, null, (function (aa) { return function () { return aa; }; })(ca)); }
    }
    var hlc = o.highlight || {};
    var cells = pool(gc, R * C, function () {
      var g = svg('g', {}); svg('rect', { rx: 4 }, g); svg('text', { class: 'cell-t', 'text-anchor': 'middle' }, g);
      return g;
    });
    for (var ii = 0; ii < R; ii++) for (var jj = 0; jj < C; jj++) {
      var g = cells[ii * C + jj], rc = g.firstChild, tx = g.lastChild, v = A[ii][jj];
      rc._heat = (function (rect, txt) { return function (tv) { var f = fillOf(tv); rect.setAttribute('fill', f); txt.style.fill = lumOf(f) > 0.5 ? '#0b0c0e' : '#f2f2f2'; }; })(rc, tx);
      rc.setAttribute('x', padL + jj * cs + 2); rc.setAttribute('y', padT + ii * cs + 2); rc.setAttribute('width', cs - 4); rc.setAttribute('height', cs - 4);
      rc.setAttribute('stroke', 'rgba(255,255,255,.06)');
      tween(rc, { heat: heatT(v) }, { from: g._new ? { heat: 0 } : null });
      tx.setAttribute('x', padL + jj * cs + cs / 2); tx.setAttribute('y', padT + ii * cs + cs / 2 + 4.5);
      tx.textContent = fmt(v, dec);
      var marked = (hlc.rows && hlc.rows.indexOf(ii) >= 0) || (hlc.cols && hlc.cols.indexOf(jj) >= 0) ||
        (hlc.cells && hlc.cells.some(function (p) { return p[0] === ii && p[1] === jj; }));
      rc.classList.toggle('mark', !!marked);
      g.dataset.i = ii; g.dataset.j = jj;
      var axs = {}; if (ax[0]) axs[ax[0]] = ii; if (ax[1]) axs[ax[1]] = jj;
      if (ax[0] || ax[1]) link(g, axs);
      (function (gi, gj, node) {
        hover(node, function () {
          var vv = (ctl ? state[o.bind] : A)[gi][gj];
          var head = (rl ? md(labelAt(rl, gi, '')) : 'row ' + (gi + 1)) + ', ' + (cl ? md(labelAt(cl, gj, '')) : 'col ' + (gj + 1));
          return head + ': <span class="tv">' + fmt(vv, 4) + '</span>' + (o.tip ? '<div class="tm">' + md(o.tip(gi, gj, vv)) + '</div>' : '');
        }, (ax[0] || ax[1]) ? function () {
          var a2 = {}, mode = o.hover || 'cell';
          if (ax[0] && mode !== 'col') a2[ax[0]] = gi;
          if (ax[1] && mode !== 'row') a2[ax[1]] = gj;
          return a2;
        } : null);
      })(ii, jj, g);
      if (changed(g, v)) pulse(rc);
      g._new = false;
    }
    s.bind = o.bind; s.cs = cs; s.padL = padL; s.padT = padT; s.R = R; s.C = C;
    if (ctl && !s.wired.drag) {
      s.wired.drag = true; s.svg.classList.add('draggable');
      dragger(s.svg, function (e, start) {
        var p = svgPt(s.svg, e), c2 = CTL[s.bind];
        if (start) {
          var ci = Math.floor((p[1] - s.padT) / s.cs), cj = Math.floor((p[0] - s.padL) / s.cs);
          if (ci < 0 || cj < 0 || ci >= s.R || cj >= s.C) return false;
          s.di = ci; s.dj = cj; s.dy0 = p[1]; s.dv0 = state[s.bind][ci][cj];
        }
        var steps = Math.round((s.dy0 - p[1]) / 5);
        setCell(s.bind, s.di, s.dj, s.dv0 + steps * c2.step);
      });
      s.svg.addEventListener('dblclick', function (e) {
        var p = svgPt(s.svg, e), ci = Math.floor((p[1] - s.padT) / s.cs), cj = Math.floor((p[0] - s.padL) / s.cs);
        if (ci < 0 || cj < 0 || ci >= s.R || cj >= s.C) return;
        var r = s.svg.getBoundingClientRect(), sc = r.width / s.W;
        var inp = el('input', 'num cell-edit'); inp.type = 'number'; inp.step = CTL[s.bind].step; inp.value = state[s.bind][ci][cj];
        inp.style.cssText = 'position:fixed;z-index:90;width:' + Math.max(56, s.cs * sc) + 'px;left:' + (r.left + (s.padL + cj * s.cs) * sc) + 'px;top:' + (r.top + (s.padT + ci * s.cs + s.cs / 2 - 14) * sc) + 'px;text-align:center';
        document.body.appendChild(inp); inp.focus(); inp.select();
        var done = false, commit = function (keep) { if (done) return; done = true; if (keep && inp.value !== '') setCell(s.bind, ci, cj, +inp.value); inp.remove(); };
        inp.addEventListener('keydown', function (ev) { if (ev.key === 'Enter') commit(true); if (ev.key === 'Escape') commit(false); });
        inp.addEventListener('blur', function () { commit(true); });
      });
    }
  };

  /* plot(target, {series:[{fn|x,y, label, sym|color, dashed, area, width, dots}], domain, xRange, yRange, points:[{x,y,label,sym}],
                   marker:{x, bind, label}, vlines:[{x,label}], hlines:[{y,label}], xLabel, yLabel, title, height, width}) */
  kit.plot = function (sel, o) {
    o = o || {};
    var fig = slot(sel, 'plot', o); if (!fig) return;
    var mk = o.marker || null, mctl = mk && mk.bind && CTL[mk.bind] ? CTL[mk.bind] : null;
    var dom = o.domain || o.xRange || null;
    var ser = asArray(o.series).map(function (sr, k) {
      var xs, ys;
      if (typeof sr.fn === 'function') {
        var d = sr.domain || dom || [0, 1];
        xs = M.linspace(d[0], d[1], sr.samples || o.samples || 220);
        ys = xs.map(function (xv) { try { var yv = sr.fn(xv); return isNum(yv) ? yv : NaN; } catch (e) { return NaN; } });
      } else {
        ys = asArray(sr.y).map(Number); xs = sr.x ? asArray(sr.x).map(Number) : ys.map(function (_, i) { return i; });
      }
      return { xs: xs, ys: ys, c: col(sr.color || sr.sym, PALETTE[SERIES[k % SERIES.length]]), label: sr.label, dashed: sr.dashed, area: sr.area, width: sr.width || 2.6, dots: sr.dots };
    });
    var pts = asArray(o.points);
    var allx = [], ally = [];
    ser.forEach(function (sr) { sr.xs.forEach(function (xv, i) { if (isNum(xv) && isNum(sr.ys[i])) { allx.push(xv); ally.push(sr.ys[i]); } }); });
    pts.forEach(function (p) { if (isNum(p.x)) allx.push(p.x); if (isNum(p.y)) ally.push(p.y); });
    asArray(o.hlines).forEach(function (h) { if (isNum(h.y)) ally.push(h.y); });
    var xr = o.xRange || dom || (allx.length ? [Math.min.apply(null, allx), Math.max.apply(null, allx)] : [0, 1]);
    if (!(xr[1] > xr[0])) xr = [xr[0] - 1, xr[0] + 1];
    var yr = o.yRange || autoRange(ally, o.zero);
    var legend = '';
    var labeled = ser.filter(function (sr) { return sr.label; });
    if (labeled.length > 1 || (labeled.length && o.legend)) legend = '<span class="legend">' + labeled.map(function (sr) { return '<span><i style="--c:' + sr.c + '"></i>' + md(sr.label) + '</span>'; }).join('') + '</span>';
    caption(fig, o.title, mctl ? '↔ drag on the plot' : '', legend);
    var W = innerW(fig), H = o.height || 260, s = frame(fig, W, H, o.title || 'plot');
    var box = { l: 52, r: W - 14, t: 12, b: H - (o.xLabel ? 46 : 28) };
    var x = lin(xr[0], xr[1], box.l, box.r), y = lin(yr[0], yr[1], box.b, box.t);
    drawAxes(s, x, y, box, o);
    if (!s.clip) {
      s.clipId = 'clip' + Math.random().toString(36).slice(2, 8);
      var defs = svg('defs', {}, s.svg); s.clipRect = svg('rect', {}, svg('clipPath', { id: s.clipId }, defs));
    }
    s.clip = true;
    s.clipRect.setAttribute('x', box.l); s.clipRect.setAttribute('y', box.t - 2); s.clipRect.setAttribute('width', box.r - box.l); s.clipRect.setAttribute('height', box.b - box.t + 4);
    var gs = layer(s, 'series'); gs.setAttribute('clip-path', 'url(#' + s.clipId + ')');
    var gx = layer(s, 'lines'), gp = layer(s, 'points'), gm = layer(s, 'marker'), gg = layer(s, 'guide');
    var base = y(clamp(0, yr[0], yr[1]));
    var paths = pool(gs, ser.length * 2, function (i) { return svg('path', { fill: 'none' }); });
    ser.forEach(function (sr, k) {
      var flat = [];
      sr.xs.forEach(function (xv, i) { var yv = sr.ys[i]; flat.push(isNum(xv) && isNum(yv) ? x(xv) : NaN, isNum(xv) && isNum(yv) ? clamp(y(yv), -4000, 4000) : NaN); });
      var ar = paths[k * 2], ln = paths[k * 2 + 1];
      if (sr.area) {
        var af = flat.slice(), fx = NaN, lx = NaN;
        for (var q = 0; q < af.length; q += 2) if (isNum(af[q])) { if (!isNum(fx)) fx = af[q]; lx = af[q]; }
        ar._closed = true; ar.setAttribute('fill', sr.c); ar.setAttribute('fill-opacity', 0.13); ar.setAttribute('stroke', 'none');
        tween(ar, { pts: [fx, base].concat(af.filter(function () { return true; }), [lx, base]) });
      } else ar.setAttribute('d', 'M0,0');
      ln.setAttribute('stroke', sr.c); ln.setAttribute('stroke-width', sr.width); ln.setAttribute('stroke-linejoin', 'round'); ln.setAttribute('stroke-linecap', 'round');
      ln.setAttribute('stroke-dasharray', sr.dashed ? '7 6' : '');
      tween(ln, { pts: flat });
    });
    gx.textContent = '';
    asArray(o.vlines).forEach(function (v) {
      if (!isNum(v.x)) return; var cc = col(v.color || v.sym, PALETTE.white), px = x(v.x);
      svg('line', { x1: px, x2: px, y1: box.t, y2: box.b, class: 'ref', stroke: cc }, gx);
      if (v.label) stext(svg('text', { x: px + 5, y: box.t + 12, class: 'reftxt', fill: cc }, gx), v.label);
    });
    asArray(o.hlines).forEach(function (h) {
      if (!isNum(h.y)) return; var cc = col(h.color || h.sym, PALETTE.white), py = y(h.y);
      svg('line', { x1: box.l, x2: box.r, y1: py, y2: py, class: 'ref', stroke: cc }, gx);
      if (h.label) stext(svg('text', { x: box.r - 4, y: py - 5, 'text-anchor': 'end', class: 'reftxt', fill: cc }, gx), h.label);
    });
    var pg = pool(gp, pts.length, function () { var g = svg('g', {}); svg('circle', { r: 6 }, g); svg('text', { class: 'lab' }, g); return g; });
    pts.forEach(function (p, i) {
      var g = pg[i], cc = col(p.color || p.sym, PALETTE.yellow), ci = g.firstChild, tt = g.lastChild;
      ci.setAttribute('fill', cc); ci.setAttribute('stroke', '#0c0d10'); ci.setAttribute('stroke-width', 2); ci.setAttribute('r', p.r || 6);
      var px = isNum(p.x) ? x(p.x) : -99, py = isNum(p.y) ? clamp(y(p.y), box.t - 30, box.b + 30) : -99;
      tween(ci, { cx: px, cy: py }, { from: g._new ? { cy: base } : null });
      stext(tt, p.label || ''); tt.style.fill = cc;
      tween(tt, { x: px + 9, y: py - 9 }, { from: g._new ? { y: base - 9 } : null });
      if (p.axis) { var pa = {}; pa[p.axis] = p.index != null ? p.index : i; link(g, pa); }
      (function (pp, node) { hover(node, function () { return (pp.label ? md(pp.label) + ': ' : '') + '(<span class="tv">' + fmt(pp.x, 3) + '</span>, <span class="tv">' + fmt(pp.y, 3) + '</span>)' + (pp.tip ? '<div class="tm">' + md(pp.tip) + '</div>' : ''); }, pp.axis ? function () { var a = {}; a[pp.axis] = pp.index != null ? pp.index : i; return a; } : null); })(p, g);
      g._new = false;
    });
    // marker: vertical line + dots on every series at x
    gm.textContent = '';
    if (mk && isNum(mk.x)) {
      var mx = x(clamp(mk.x, xr[0], xr[1])), mc = col(mk.color || mk.sym, PALETTE.yellow);
      svg('line', { x1: mx, x2: mx, y1: box.t, y2: box.b, stroke: mc, 'stroke-width': 1.5, 'stroke-dasharray': '4 4' }, gm);
      ser.forEach(function (sr) {
        var yv = interpAt(sr.xs, sr.ys, mk.x);
        if (isNum(yv)) svg('circle', { cx: mx, cy: y(yv), r: 5.5, fill: sr.c, stroke: '#0c0d10', 'stroke-width': 2 }, gm);
      });
      var lbl = (mk.label || '{x}') + ' = ' + fmt(mk.x, mctl ? decimalsOf(mctl.step) : 3);
      var tx = svg('text', { x: mx + (mx > (box.l + box.r) / 2 ? -7 : 7), y: box.b - 8, 'text-anchor': mx > (box.l + box.r) / 2 ? 'end' : 'start', class: 'val', fill: mc }, gm);
      stext(tx, lbl);
      if (mctl) svg('path', { d: 'M' + (mx - 7) + ',' + (box.b + 1) + 'L' + (mx + 7) + ',' + (box.b + 1) + 'L' + mx + ',' + (box.b - 9) + 'Z', fill: mc }, gm);
    }
    s.x = x; s.y = y; s.box = box; s.ser = ser; s.mk = mk;
    if (mctl && !s.wired.drag) {
      s.wired.drag = true; s.svg.classList.add('hdrag');
      dragger(s.svg, function (e, start) {
        var p = svgPt(s.svg, e);
        if (start && (p[0] < s.box.l - 6 || p[0] > s.box.r + 6 || p[1] < s.box.t - 6 || p[1] > s.box.b + 20)) return false;
        setControl(s.mk.bind, s.x.inv(p[0]));
      });
    }
    if (!s.wired.hover) {
      s.wired.hover = true;
      s.svg.addEventListener('pointermove', function (e) {
        if (DRAG) return;
        var p = svgPt(s.svg, e), b = s.box; gg.textContent = '';
        if (p[0] < b.l || p[0] > b.r || p[1] < b.t || p[1] > b.b) { hideTip(); return; }
        var xv = s.x.inv(p[0]);
        svg('line', { x1: p[0], x2: p[0], y1: b.t, y2: b.b, class: 'guide' }, gg);
        var rows = s.ser.map(function (sr) { var yv = interpAt(sr.xs, sr.ys, xv); return isNum(yv) ? '<div><i style="display:inline-block;width:10px;height:3px;background:' + sr.c + ';vertical-align:3px;margin-right:6px"></i>' + (sr.label ? md(sr.label) + ' = ' : '') + '<span class="tv">' + fmt(yv, 4) + '</span></div>' : ''; }).join('');
        showTip('<div class="tm">x = ' + fmt(xv, 3) + '</div>' + rows, e);
      });
      s.svg.addEventListener('pointerleave', function () { gg.textContent = ''; hideTip(); });
    }
  };
  function interpAt(xs, ys, xv) {
    var n = xs.length; if (!n) return NaN;
    if (xv <= xs[0]) return xv === xs[0] ? ys[0] : NaN;
    if (xv >= xs[n - 1]) return xv === xs[n - 1] ? ys[n - 1] : NaN;
    var lo = 0, hi = n - 1;
    while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (xs[mid] <= xv) lo = mid; else hi = mid; }
    var t = (xv - xs[lo]) / ((xs[hi] - xs[lo]) || 1);
    return ys[lo] + (ys[hi] - ys[lo]) * t;
  }

  /* plane(target, {range:[x0,x1,y0,y1], vectors:[{x,y,from,label,sym|color,bind,dashed}], points:[{x,y,label,sym,bind}],
                    segments:[{from,to,sym,dashed,label}], polygons:[{points,sym,label}], title, height, width}) */
  kit.plane = function (sel, o) {
    o = o || {};
    var fig = slot(sel, 'plane', o); if (!fig) return;
    var rg = o.range || [-4, 4, -3, 3];
    var anyBind = asArray(o.vectors).concat(asArray(o.points)).some(function (v) { return v.bind; });
    caption(fig, o.title, anyBind ? '✥ drag the arrow tips' : '');
    var maxW = Math.min(o.width ? innerW(fig) : availW(fig), o.maxWidth || 640), maxH = o.height || 340;
    var unit = Math.min((maxW - 28) / (rg[1] - rg[0]), (maxH - 28) / (rg[3] - rg[2]));
    var W = Math.round(unit * (rg[1] - rg[0]) + 28), H = Math.round(unit * (rg[3] - rg[2]) + 28);
    var s = frame(fig, W, H, o.title || 'coordinate plane');
    var x = lin(rg[0], rg[1], 14, W - 14), y = lin(rg[2], rg[3], H - 14, 14);
    if (!s.gridDone) {
      s.gridDone = true;
      var g = layer(s, 'grid');
      var stepG = (rg[1] - rg[0]) > 24 ? 5 : 1;
      for (var gx = Math.ceil(rg[0] * 2) / 2; gx <= rg[1]; gx += 0.5) svg('line', { x1: x(gx), x2: x(gx), y1: y(rg[2]), y2: y(rg[3]), class: Math.abs(gx % stepG) < 1e-9 ? 'pgrid' : 'pgrid2' }, g);
      for (var gy = Math.ceil(rg[2] * 2) / 2; gy <= rg[3]; gy += 0.5) svg('line', { x1: x(rg[0]), x2: x(rg[1]), y1: y(gy), y2: y(gy), class: Math.abs(gy % stepG) < 1e-9 ? 'pgrid' : 'pgrid2' }, g);
      if (rg[0] <= 0 && rg[1] >= 0) svg('line', { x1: x(0), x2: x(0), y1: y(rg[2]), y2: y(rg[3]), class: 'paxis' }, g);
      if (rg[2] <= 0 && rg[3] >= 0) svg('line', { x1: x(rg[0]), x2: x(rg[1]), y1: y(0), y2: y(0), class: 'paxis' }, g);
      for (var tx = Math.ceil(rg[0]); tx <= rg[1]; tx += stepG) if (tx !== 0) svg('text', { x: x(tx), y: y(0) + 15, 'text-anchor': 'middle', class: 'tick' }, g).textContent = tx;
      for (var ty = Math.ceil(rg[2]); ty <= rg[3]; ty += stepG) if (ty !== 0) svg('text', { x: x(0) - 6, y: y(ty) + 4, 'text-anchor': 'end', class: 'tick' }, g).textContent = ty;
    }
    var gpoly = layer(s, 'poly'), gseg = layer(s, 'seg'), gv = layer(s, 'vec'), gpt = layer(s, 'pts');
    var polys = asArray(o.polygons);
    var pp = pool(gpoly, polys.length, function () { var p = svg('path', {}); p._closed = true; return p; });
    polys.forEach(function (pl, i) {
      var cc = col(pl.color || pl.sym, PALETTE.white), flat = [];
      asArray(pl.points).forEach(function (q) { flat.push(x(q[0]), y(q[1])); });
      pp[i].setAttribute('fill', cc); pp[i].setAttribute('fill-opacity', pl.opacity != null ? pl.opacity : 0.1); pp[i].setAttribute('stroke', cc); pp[i].setAttribute('stroke-opacity', 0.45); pp[i].setAttribute('stroke-dasharray', '4 4');
      tween(pp[i], { pts: flat });
    });
    var segs = asArray(o.segments);
    var sp = pool(gseg, segs.length, function () { return svg('line', {}); });
    segs.forEach(function (sg, i) {
      var cc = col(sg.color || sg.sym, PALETTE.white);
      sp[i].setAttribute('stroke', cc); sp[i].setAttribute('stroke-width', sg.width || 1.6); sp[i].setAttribute('stroke-dasharray', sg.dashed === false ? '' : '5 5'); sp[i].setAttribute('opacity', 0.75);
      tween(sp[i], { x1: x(sg.from[0]), y1: y(sg.from[1]), x2: x(sg.to[0]), y2: y(sg.to[1]) });
    });
    var vecs = asArray(o.vectors);
    var vn = pool(gv, vecs.length, function () {
      var a = arrowNode(null, 'arrow'); var lab = svg('text', { class: 'lab', 'text-anchor': 'middle' }, a); var hd = svg('circle', { r: 7, class: 'handle free' }, a);
      a._after = function (x2, y2, ux, uy) { lab.setAttribute('x', x2 + ux * 16 + (Math.abs(uy) > 0.7 ? 12 : 0)); lab.setAttribute('y', y2 + uy * 16 + 5); hd.setAttribute('cx', x2); hd.setAttribute('cy', y2); };
      a._lab = lab; a._hd = hd; return a;
    });
    vecs.forEach(function (v, i) {
      var a = vn[i], cc = col(v.color || v.sym, PALETTE[SERIES[i % SERIES.length]]);
      var xy = v.bind ? bindGet(v.bind) : [v.x, v.y];
      if (!xy || !isNum(xy[0]) || !isNum(xy[1])) xy = [isNum(v.x) ? v.x : 0, isNum(v.y) ? v.y : 0];
      var f = v.from || [0, 0];
      a._style(cc, v.width || 3.2, v.dashed, v.opacity);
      stext(a._lab, v.label || ''); a._lab.style.fill = cc;
      a._hd.style.display = v.bind ? '' : 'none'; a._hd.setAttribute('stroke', cc);
      tween(a, { vec: [x(f[0]), y(f[1]), x(xy[0]), y(xy[1])] }, { from: a._new ? { vec: [x(f[0]), y(f[1]), x(f[0]) + 0.01, y(f[1])] } : null });
      if (v.axis) { var va = {}; va[v.axis] = v.index != null ? v.index : i; link(a, va); }
      (function (vv, node, ii) { hover(node, function () { var q = vv.bind ? bindGet(vv.bind) : [vv.x, vv.y]; return (vv.label ? md(vv.label) + ' = ' : '') + '(<span class="tv">' + fmt(q[0], 3) + '</span>, <span class="tv">' + fmt(q[1], 3) + '</span>)' + (vv.tip ? '<div class="tm">' + md(vv.tip) + '</div>' : ''); }, vv.axis ? function () { var aa = {}; aa[vv.axis] = vv.index != null ? vv.index : ii; return aa; } : null); })(v, a, i);
      a._bind = v.bind; a._x = x; a._y = y;
      if (v.bind && !a._dw) { a._dw = true; dragger(a._hd, function (e) { var p = svgPt(s.svg, e); bindSet(a._bind, [a._x.inv(p[0]), a._y.inv(p[1])]); }); }
      a._new = false;
    });
    var pts = asArray(o.points);
    var pn = pool(gpt, pts.length, function () { var g = svg('g', {}); svg('circle', { r: 6 }, g); svg('text', { class: 'lab' }, g); return g; });
    pts.forEach(function (p, i) {
      var g = pn[i], cc = col(p.color || p.sym, PALETTE.yellow), ci = g.firstChild, tt = g.lastChild;
      var xy = p.bind ? bindGet(p.bind) : [p.x, p.y]; if (!xy) xy = [0, 0];
      ci.setAttribute('fill', cc); ci.setAttribute('stroke', '#0c0d10'); ci.setAttribute('stroke-width', 2); ci.setAttribute('r', p.r || 6);
      if (p.bind) ci.classList.add('handle', 'free');
      tween(ci, { cx: x(xy[0]), cy: y(xy[1]) }, { from: g._new ? { cx: x(0), cy: y(0) } : null });
      stext(tt, p.label || ''); tt.style.fill = cc;
      tween(tt, { x: x(xy[0]) + 10, y: y(xy[1]) - 10 }, { from: g._new ? { x: x(0) + 10, y: y(0) - 10 } : null });
      if (p.axis) { var pa = {}; pa[p.axis] = p.index != null ? p.index : i; link(g, pa); }
      (function (pp2, node, ii) { hover(node, function () { var q = pp2.bind ? bindGet(pp2.bind) : [pp2.x, pp2.y]; return (pp2.label ? md(pp2.label) + ' = ' : '') + '(<span class="tv">' + fmt(q[0], 3) + '</span>, <span class="tv">' + fmt(q[1], 3) + '</span>)' + (pp2.tip ? '<div class="tm">' + md(pp2.tip) + '</div>' : ''); }, pp2.axis ? function () { var aa = {}; aa[pp2.axis] = pp2.index != null ? pp2.index : ii; return aa; } : null); })(p, g, i);
      g._bind = p.bind; g._x = x; g._y = y;
      if (p.bind && !g._dw) { g._dw = true; dragger(ci, function (e) { var q = svgPt(s.svg, e); bindSet(g._bind, [g._x.inv(q[0]), g._y.inv(q[1])]); }); }
      g._new = false;
    });
  };

  /* graph(target, {nodes:[{id,label,value,sym|color}], edges:[{from,to,weight,label}], layout:'circle'|'line'|'tree'|'grid',
                    positions:{id:[x,y] in 0..1}, directed, axis:'node', title, height, width, decimals}) */
  kit.graph = function (sel, o) {
    o = o || {};
    var fig = slot(sel, 'graph', o); if (!fig) return;
    caption(fig, o.title, '✥ drag nodes to rearrange');
    var nodes = asArray(o.nodes), edges = asArray(o.edges), N = nodes.length;
    var W = innerW(fig), H = o.height || 320, s = frame(fig, W, H, o.title || 'graph');
    var idx = {}; nodes.forEach(function (nd, i) { idx[nd.id != null ? nd.id : i] = i; });
    var pos = layoutGraph(nodes, edges, idx, o.layout, o.positions);
    s.pos = s.pos || {};
    var pad = 42, X = function (u) { return pad + u * (W - 2 * pad); }, Y = function (u) { return pad + u * (H - 2 * pad); };
    var vals = nodes.map(function (nd) { return Number(nd.value); }), hasV = vals.some(isNum);
    var vmax = hasV ? Math.max.apply(null, vals.filter(isNum).map(Math.abs)) || 1 : 1;
    var rad = function (v) { return hasV && isNum(v) ? 12 + 20 * Math.sqrt(Math.abs(v) / vmax) : 18; };
    var ws = edges.map(function (e) { return Number(e.weight); }), wmax = Math.max.apply(null, ws.filter(isNum).map(Math.abs).concat([1e-9]));
    var axis = o.axis || 'node';
    var P = nodes.map(function (nd, i) { var key = nd.id != null ? nd.id : i, q = s.pos[key] || pos[i]; return [X(q[0]), Y(q[1])]; });
    var ge = layer(s, 'edges'), gn = layer(s, 'nodes');
    var en = pool(ge, edges.length, function () { var g = svg('g', {}); svg('path', { fill: 'none' }, g); svg('polygon', {}, g); svg('text', { class: 'lab', 'text-anchor': 'middle' }, g); return g; });
    var pairs = {}; edges.forEach(function (e) { pairs[idx[e.from] + '>' + idx[e.to]] = 1; });
    edges.forEach(function (e, k) {
      var g = en[k], a = idx[e.from], b = idx[e.to];
      if (a == null || b == null) { g.style.display = 'none'; return; } g.style.display = '';
      var c = col(e.color || e.sym || o.edgeColor, PALETTE.grey), w = Number(e.weight), wn = isNum(w) ? Math.abs(w) / wmax : 0.5;
      var A = P[a], B = P[b], dx = B[0] - A[0], dy = B[1] - A[1], L = Math.hypot(dx, dy) || 1, ux = dx / L, uy = dy / L;
      var bend = pairs[b + '>' + a] && o.directed !== false ? 18 : 0;
      var mx = (A[0] + B[0]) / 2 - uy * bend, my = (A[1] + B[1]) / 2 + ux * bend;
      var ra = rad(vals[a]) + 2, rb = rad(vals[b]) + 4;
      var sx = A[0] + ux * ra, sy = A[1] + uy * ra, tx = B[0] - ux * rb, ty = B[1] - uy * rb;
      var path = g.childNodes[0], head = g.childNodes[1], lab = g.childNodes[2];
      path.setAttribute('d', 'M' + sx + ',' + sy + 'Q' + mx + ',' + my + ' ' + tx + ',' + ty);
      path.setAttribute('stroke', c); path.setAttribute('stroke-opacity', 0.35 + 0.6 * wn);
      tween(path, { 'stroke-width': 1.2 + 4.5 * wn });
      if (o.directed !== false) {
        var hx = tx - mx, hy = ty - my, hL = Math.hypot(hx, hy) || 1, vx = hx / hL, vy = hy / hL, hl = 10, hw = 5;
        head.setAttribute('points', tx + ',' + ty + ' ' + (tx - vx * hl - vy * hw) + ',' + (ty - vy * hl + vx * hw) + ' ' + (tx - vx * hl + vy * hw) + ',' + (ty - vy * hl - vx * hw));
        head.setAttribute('fill', c); head.setAttribute('fill-opacity', 0.5 + 0.5 * wn);
      } else head.setAttribute('points', '');
      var showL = e.label != null || (o.edgeLabels && isNum(w));
      stext(lab, showL ? (e.label != null ? e.label : fmt(w, o.decimals != null ? o.decimals : 2)) : '');
      lab.setAttribute('x', (sx + 2 * mx + tx) / 4 - uy * 9); lab.setAttribute('y', (sy + 2 * my + ty) / 4 + ux * 9 + 4);
      var ea1 = {}, ea2 = {}; ea1[axis] = a; ea2[axis] = b; link(g, [ea1, ea2]);
    });
    var nn = pool(gn, N, function () { var g = svg('g', { class: 'gnode' }); svg('circle', {}, g); svg('text', { class: 'val', 'text-anchor': 'middle' }, g); svg('text', { class: 'lab', 'text-anchor': 'middle' }, g); return g; });
    nodes.forEach(function (nd, i) {
      var g = nn[i], ci = g.childNodes[0], tv = g.childNodes[1], tl = g.childNodes[2], c = col(nd.color || nd.sym || o.color || o.sym, PALETTE.blue);
      var r = rad(vals[i]);
      ci.setAttribute('fill', mix('#16191f', c, 0.35)); ci.setAttribute('stroke', c); ci.setAttribute('stroke-width', 2.2);
      ci.setAttribute('cx', P[i][0]); ci.setAttribute('cy', P[i][1]);
      tween(ci, { r: r }, { from: g._new ? { r: 0 } : null });
      tv.setAttribute('x', P[i][0]); tv.setAttribute('y', P[i][1] + 4);
      tv.textContent = hasV && isNum(vals[i]) ? fmt(vals[i], o.decimals != null ? o.decimals : 2) : '';
      stext(tl, nd.label != null ? nd.label : String(nd.id != null ? nd.id : i)); tl.setAttribute('x', P[i][0]); tl.setAttribute('y', P[i][1] - r - 7); tl.style.fill = c;
      var na = {}; na[axis] = i; link(g, na);
      (function (ii, nd2, node) {
        hover(node, function () { return md(nd2.label != null ? nd2.label : nd2.id) + (hasV ? ': <span class="tv">' + fmt(Number(nd2.value), 4) + '</span>' : '') + (nd2.tip ? '<div class="tm">' + md(nd2.tip) + '</div>' : ''); }, function () { var a = {}; a[axis] = ii; return a; });
      })(i, nd, g);
      if (changed(g, vals[i])) pulse(ci);
      g._key = nd.id != null ? nd.id : i;
      if (!g._dw) {
        g._dw = true; g.style.cursor = 'grab';
        dragger(g, function (e) { var p = svgPt(s.svg, e); s.pos[g._key] = [clamp((p[0] - pad) / (W - 2 * pad), -0.05, 1.05), clamp((p[1] - pad) / (H - 2 * pad), -0.05, 1.05)]; scheduleUpdate(); });
      }
      g._new = false;
    });
  };
  function layoutGraph(nodes, edges, idx, layout, given) {
    var N = nodes.length, pos = [];
    if (given) return nodes.map(function (nd, i) { var q = given[nd.id != null ? nd.id : i]; return q ? [clamp(q[0], 0, 1), clamp(q[1], 0, 1)] : [0.5, 0.5]; });
    if (layout === 'line') return nodes.map(function (_, i) { return [N > 1 ? i / (N - 1) : 0.5, 0.5]; });
    if (layout === 'grid') { var cN = Math.ceil(Math.sqrt(N)), rN = Math.ceil(N / cN); return nodes.map(function (_, i) { return [cN > 1 ? (i % cN) / (cN - 1) : 0.5, rN > 1 ? Math.floor(i / cN) / (rN - 1) : 0.5]; }); }
    if (layout === 'tree') {
      var indeg = nodes.map(function () { return 0; }), ch = nodes.map(function () { return []; });
      edges.forEach(function (e) { var a = idx[e.from], b = idx[e.to]; if (a != null && b != null) { indeg[b]++; ch[a].push(b); } });
      var lvl = nodes.map(function () { return -1; }), q = [];
      indeg.forEach(function (d, i) { if (d === 0) { lvl[i] = 0; q.push(i); } });
      if (!q.length) { lvl[0] = 0; q.push(0); }
      while (q.length) { var u = q.shift(); ch[u].forEach(function (v) { if (lvl[v] < 0) { lvl[v] = lvl[u] + 1; q.push(v); } }); }
      lvl = lvl.map(function (l) { return l < 0 ? 0 : l; });
      var maxL = Math.max.apply(null, lvl), rows = {};
      lvl.forEach(function (l, i) { (rows[l] = rows[l] || []).push(i); });
      lvl.forEach(function (l, i) { var r = rows[l], k = r.indexOf(i); pos[i] = [(k + 1) / (r.length + 1), maxL ? l / maxL : 0.5]; });
      return pos;
    }
    return nodes.map(function (_, i) { var a = -Math.PI / 2 + 2 * Math.PI * i / Math.max(N, 1); return [0.5 + 0.5 * Math.cos(a), 0.5 + 0.5 * Math.sin(a)]; });
  }

  /* steps(target, [{label, value, sym|color, op, note, unit, decimals}], {title}) — the chain of intermediate values */
  kit.steps = function (sel, items, o) {
    o = o || {};
    var fig = slot(sel, 'steps', o); if (!fig) return;
    caption(fig, o.title, '');
    items = asArray(items).map(function (it) { return Array.isArray(it) ? { label: it[0], value: it[1], unit: it[2] } : it || {}; });
    var row = fig._row || (fig._row = el('div', 'steps', fig));
    if (row._n !== items.length) {
      row.textContent = ''; row._n = items.length;
      items.forEach(function (_, i) {
        if (i) el('div', 'step-arrow', row, '<span class="op"></span><span class="ar">&#10230;</span>');
        el('div', 'step', row, '<div class="lbl"></div><div class="v"></div><div class="nt"></div>');
      });
    }
    var cards = row.querySelectorAll('.step'), arrows = row.querySelectorAll('.step-arrow');
    items.forEach(function (it, i) {
      var card = cards[i], c = it.color || it.sym ? col(it.color || it.sym) : null;
      card.style.setProperty('--c', c || 'var(--line2)');
      if (it.sym) card.dataset.sym = symKey(it.sym) || it.sym;
      setHTML(card.children[0], md(it.label));
      if (setHTML(card.children[1], valueHTML(it.value, it.decimals != null ? it.decimals : o.decimals, it.unit))) pulse(card);
      setHTML(card.children[2], md(it.note || ''));
      if (i) setHTML(arrows[i - 1].querySelector('.op'), md(it.op || ''));
    });
  };
  function valueHTML(v, d, unit) {
    var u = unit ? '<span class="u">' + md(unit) + '</span>' : '';
    if (Array.isArray(v) && Array.isArray(v[0])) return '<table class="mini">' + v.map(function (r) { return '<tr>' + r.map(function (x) { return '<td>' + fmt(x, d != null ? d : 2) + '</td>'; }).join('') + '</tr>'; }).join('') + '</table>' + u;
    if (Array.isArray(v)) return '[' + v.map(function (x) { return fmt(x, d != null ? d : 2); }).join(', ') + ']' + u;
    if (typeof v === 'number') return fmt(v, d) + u;
    if (typeof v === 'boolean') return (v ? 'yes' : 'no') + u;
    return md(v == null ? '' : v) + u;
  }

  /* readout(target, {label, value, sym|color, unit, decimals, min, max, compare:{value,label}, note}) — one big live number */
  kit.readout = function (sel, o) {
    o = o || {};
    var fig = slot(sel, 'readout', o); if (!fig) return;
    if (!fig._b) fig._b = el('div', 'ro', fig, '<div class="ro-l"></div><div class="ro-v"><span class="n"></span><span class="u"></span></div><div class="gauge"><div class="fill"></div><div class="cmp"><span></span></div><div class="ends"><span></span><span></span></div></div><div class="ro-n"></div>');
    var b = fig._b, c = compColor(o);
    fig.style.setProperty('--c', c);
    setHTML(b.querySelector('.ro-l'), md(o.label || ''));
    var num = b.querySelector('.n'), d = o.decimals != null ? o.decimals : 3;
    countTo(num, Number(o.value), d);
    setHTML(b.querySelector('.u'), md(o.unit || ''));
    var gauge = b.querySelector('.gauge');
    if (isNum(o.max)) {
      var lo = isNum(o.min) ? o.min : 0, span = (o.max - lo) || 1;
      gauge.style.display = '';
      b.querySelector('.fill').style.width = clamp((Number(o.value) - lo) / span, 0, 1) * 100 + '%';
      var cmp = b.querySelector('.cmp');
      if (o.compare && isNum(o.compare.value)) {
        var cf = clamp((o.compare.value - lo) / span, 0, 1);
        cmp.style.display = ''; cmp.style.left = cf * 100 + '%'; cmp.classList.toggle('end', cf > 0.7); cmp.classList.toggle('start', cf < 0.3);
        setHTML(cmp.firstChild, md(o.compare.label || ''));
      }
      else cmp.style.display = 'none';
      var ends = b.querySelectorAll('.ends span'); ends[0].textContent = fmt(lo); ends[1].textContent = fmt(o.max, d);
    } else gauge.style.display = 'none';
    setHTML(b.querySelector('.ro-n'), md(o.note || ''));
    if (changed(fig, Number(o.value))) pulse(num);
  };
  function countTo(span, v, d) {
    var prev = span._v; span._v = v; span.dataset.value = String(v);
    cancelAnimationFrame(span._raf);
    if (!isNum(v) || !isNum(prev) || FAST || REDUCED) { span.textContent = fmt(v, d); return; }
    var t0 = performance.now();
    var stp = function (now) {
      var t = Math.min(1, (now - t0) / 380);
      span.textContent = t < 1 ? fmt(prev + (v - prev) * ease(t), d) : fmt(v, d);
      if (t < 1) span._raf = requestAnimationFrame(stp);
    };
    span._raf = requestAnimationFrame(stp);
  }

  /* formula(target, markup) — a live equation with current numbers substituted; note(target, markup) — dynamic sentence */
  kit.formula = function (sel, text, o) { var fig = slot(sel, 'formula', o || {}); if (!fig) return; var d = fig._d || (fig._d = el('div', 'eq-live', fig)); setHTML(d, md(text)); };
  kit.note = function (sel, text, o) { var fig = slot(sel, 'note', o || {}); if (!fig) return; var d = fig._d || (fig._d = el('p', 'note', fig)); setHTML(d, md(text)); };

  /* svg(target, draw(g), {xRange, yRange, height, axes, grid, equal, title, width}) — escape hatch with pre-styled primitives.
     g.line/arrow(x1,y1,x2,y2,st)  g.circle(x,y,rPx,st)  g.rect(x,y,w,h,st)  g.text(x,y,str,st)  g.path(pts,st)  g.polygon(pts,st)
     st = {sym|color, width, dashed, fill, opacity, size, anchor, tip} */
  kit.svg = function (sel, draw, o) {
    o = o || {};
    var fig = slot(sel, 'svg', o); if (!fig) return;
    caption(fig, o.title, '');
    var xr = o.xRange || [0, 10], yr = o.yRange || [0, 10];
    var W = innerW(fig), H = o.height || 260;
    if (o.equal) { var u = Math.min((W - 20) / (xr[1] - xr[0]), (H - 20) / (yr[1] - yr[0])); W = Math.round(u * (xr[1] - xr[0]) + 20); H = Math.round(u * (yr[1] - yr[0]) + 20); }
    var s = frame(fig, W, H, o.title || 'diagram');
    var box = { l: o.axes ? 46 : 10, r: W - 10, t: 10, b: H - (o.axes ? (o.xLabel ? 46 : 28) : 10) };
    var x = lin(xr[0], xr[1], box.l, box.r), y = lin(yr[0], yr[1], box.b, box.t);
    if (o.axes || o.grid) drawAxes(s, x, y, box, o); else if (s.layers.axes) s.layers.axes.textContent = '';
    var items = [];
    var fp = function (pts) { var f = []; asArray(pts).forEach(function (q) { f.push(x(q[0]), y(q[1])); }); return f; };
    var g = {
      line: function (a, b, c2, d, st) { items.push({ t: 'line', a: { x1: x(a), y1: y(b), x2: x(c2), y2: y(d) }, st: st || {} }); },
      arrow: function (a, b, c2, d, st) { items.push({ t: 'arrow', a: { vec: [x(a), y(b), x(c2), y(d)] }, st: st || {} }); },
      circle: function (cx, cy, r, st) { items.push({ t: 'circle', a: { cx: x(cx), cy: y(cy), r: r == null ? 5 : r }, st: st || {} }); },
      rect: function (rx, ry, w, h, st) { var X0 = x(rx), X1 = x(rx + w), Y0 = y(ry), Y1 = y(ry + h); items.push({ t: 'rect', a: { x: Math.min(X0, X1), y: Math.min(Y0, Y1), width: Math.abs(X1 - X0), height: Math.abs(Y1 - Y0) }, st: st || {} }); },
      text: function (tx, ty, str, st) { items.push({ t: 'text', a: { x: x(tx), y: y(ty) }, str: str, st: st || {} }); },
      path: function (pts, st) { items.push({ t: 'path', a: { pts: fp(pts) }, st: st || {} }); },
      polygon: function (pts, st) { items.push({ t: 'polygon', a: { pts: fp(pts) }, st: st || {} }); },
      x: x, y: y, W: W, H: H, color: col, fmt: fmt
    };
    try { draw(g); } catch (e) { note('render', 'kit.svg drawing failed: ' + e.message); }
    var gi = layer(s, 'items'), kids = gi._kids || (gi._kids = []);
    items.forEach(function (it, i) {
      var n = kids[i];
      if (!n || n._t !== it.t) {
        var nn = it.t === 'arrow' ? arrowNode(null) : it.t === 'polygon' ? svg('path', {}) : svg(it.t === 'path' ? 'path' : it.t, {});
        nn._t = it.t; nn._new = true; if (it.t === 'polygon') nn._closed = true;
        if (n) gi.replaceChild(nn, n); else gi.appendChild(nn);
        kids[i] = n = nn;
      }
      var st = it.st, c = col(st.color || st.sym, PALETTE.white);
      if (it.t === 'arrow') n._style(c, st.width || 2.6, st.dashed, st.opacity);
      else if (it.t === 'text') { stext(n, it.str); n.style.fill = c; n.setAttribute('text-anchor', st.anchor || 'middle'); n.setAttribute('font-size', st.size || 13); n.setAttribute('class', 'lab'); }
      else {
        n.setAttribute('stroke', st.stroke === false ? 'none' : c); n.setAttribute('stroke-width', st.width || 2);
        n.setAttribute('stroke-dasharray', st.dashed ? '6 5' : '');
        var fill = st.fill ? (st.fill === true ? c : col(st.fill, c)) : (it.t === 'circle' ? c : 'none');
        n.setAttribute('fill', fill); n.setAttribute('fill-opacity', st.fillOpacity != null ? st.fillOpacity : (st.fill || it.t === 'circle' ? (it.t === 'circle' ? 1 : 0.25) : 1));
        if (it.t === 'rect') n.setAttribute('rx', st.rx != null ? st.rx : 3);
      }
      n.setAttribute('opacity', st.opacity != null ? st.opacity : 1);
      var from = null;
      if (n._new) {
        if (it.t === 'arrow') from = { vec: [it.a.vec[0], it.a.vec[1], it.a.vec[0] + 0.01, it.a.vec[1]] };
        else if (it.t === 'circle') from = { r: 0 };
        else if (it.t === 'rect') from = { height: 0, y: it.a.y + it.a.height };
      }
      tween(n, it.a, { from: from });
      if (st.tip) hover(n, (function (tp) { return function () { return md(tp); }; })(st.tip), null);
      n._new = false;
    });
    while (kids.length > items.length) kids.pop().remove();
  };

  // ================================================================== CONTROLS
  function num(v, d) { var n = Number(v); return isNum(n) ? n : d; }
  var TYPE_ALIAS = { range: 'slider', number: 'slider', int: 'slider', integer: 'slider', float: 'slider', scalar: 'slider', checkbox: 'toggle', boolean: 'toggle', bool: 'toggle',
    switch: 'toggle', radio: 'select', dropdown: 'select', choice: 'select', distribution: 'simplex', probabilities: 'simplex', probability: 'simplex', grid: 'matrix',
    animate: 'play', time: 'play', step: 'play', array: 'vector', list: 'vector' };
  function normCtl(raw) {
    var c = Object.assign({}, raw);
    c.id = String(c.id);
    var t = String(c.type || c.kind || 'slider').toLowerCase(); c.type = TYPE_ALIAS[t] || t;
    if (['slider', 'play', 'toggle', 'select', 'vector', 'simplex', 'matrix'].indexOf(c.type) < 0) c.type = Array.isArray(c.value) ? (Array.isArray(c.value[0]) ? 'matrix' : 'vector') : typeof c.value === 'boolean' ? 'toggle' : 'slider';
    if (c.type === 'slider' || c.type === 'play') {
      c.min = num(c.min, 0); c.max = num(c.max, Math.max(c.min + 1, num(c.value, 1))); if (c.max <= c.min) c.max = c.min + 1;
      c.step = num(c.step, niceStep(c.max - c.min)); if (c.step <= 0) c.step = niceStep(c.max - c.min);
      c.value = num(c.value, c.min);
    } else if (c.type === 'vector' || c.type === 'simplex' || c.type === 'matrix') {
      if (c.type === 'simplex') { c.min = 0; c.max = 1; c.step = num(c.step, 0.01); }
      else {
        var flat = [].concat.apply([], asArray(c.value).map(asArray)).map(Number).filter(isNum);
        var vmin = flat.length ? Math.min.apply(null, flat) : 0, vmax = flat.length ? Math.max.apply(null, flat) : 1;
        c.min = num(c.min, Math.min(vmin, vmin < 0 ? -Math.max(1, Math.abs(vmax), Math.abs(vmin)) * 2 : 0));
        c.max = num(c.max, Math.max(1, Math.abs(vmax), Math.abs(vmin)) * 2); if (c.max <= c.min) c.max = c.min + 1;
        c.step = num(c.step, niceStep(c.max - c.min));
      }
      if (!Array.isArray(c.value)) c.value = c.type === 'matrix' ? [[0, 0], [0, 0]] : [1, 1, 1];
    } else if (c.type === 'toggle') c.value = !!c.value;
    else if (c.type === 'select') {
      c.options = asArray(c.options).map(function (op) { return op && typeof op === 'object' ? { value: op.value, label: op.label != null ? op.label : String(op.value) } : { value: op, label: String(op) }; });
      if (!c.options.length) c.options = [{ value: c.value, label: String(c.value) }];
      if (!c.options.some(function (op) { return op.value === c.value; })) c.value = c.options[0].value;
    }
    return c;
  }
  function snap(c, v) {
    v = Number(v); if (!isNum(v)) return null;
    v = clamp(v, c.min, c.max);
    if (c.step) { var d = Math.max(decimalsOf(c.step), decimalsOf(c.min)); v = +(c.min + Math.round((v - c.min) / c.step) * c.step).toFixed(Math.min(12, d + 1)); v = +v.toFixed(Math.min(12, d)); }
    return clamp(v, c.min, c.max);
  }
  function lenOf(c, cur) {
    if (isNum(c.length)) return c.length;
    if (typeof c.length === 'string' && CTL[c.length] && isNum(state[c.length])) return Math.max(1, Math.round(state[c.length]));
    return (cur || c.value).length;
  }
  function dimOf(c, key, cur, fallback) {
    var v = c[key];
    if (isNum(v)) return v;
    if (typeof v === 'string' && CTL[v] && isNum(state[v])) return Math.max(1, Math.round(state[v]));
    return fallback;
  }
  function resizeVec(c, arr, L) {
    arr = arr.slice(0, L);
    var dflt = DEFAULTS[c.id] || c.value;
    while (arr.length < L) {
      if (c.type === 'simplex') arr.push(arr.length ? M.mean(arr) : 1);
      else arr.push(dflt && isNum(dflt[arr.length]) ? dflt[arr.length] : (c.fill != null ? c.fill : clamp(0, c.min, c.max)));
    }
    return arr;
  }
  function sanitize(c, v, old) {
    if (c.type === 'slider' || c.type === 'play') { var s = snap(c, v); return s == null ? old : s; }
    if (c.type === 'toggle') return !!v;
    if (c.type === 'select') { var hit = c.options.filter(function (op) { return op.value === v || String(op.value) === String(v); })[0]; return hit ? hit.value : old; }
    if (c.type === 'vector' || c.type === 'simplex') {
      var arr = asArray(v).map(Number), L = lenOf(c, arr);
      arr = resizeVec(c, arr.map(function (x, i) { return isNum(x) ? x : (old && isNum(old[i]) ? old[i] : 0); }), L);
      if (c.type === 'simplex') {
        arr = arr.map(function (x) { return Math.max(0, x); });
        var sm = M.sum(arr);
        if (Math.abs(sm - 1) > 1e-9) arr = M.normalize(arr);
        return arr;
      }
      return arr.map(function (x) { var q = snap(c, x); return q == null ? 0 : q; });
    }
    if (c.type === 'matrix') {
      var A = asArray(v).map(function (r) { return asArray(r).map(Number); });
      var R = dimOf(c, 'rows', null, A.length), C = dimOf(c, 'cols', null, A[0] ? A[0].length : 1);
      var out = [];
      for (var i = 0; i < R; i++) { var row = []; for (var j = 0; j < C; j++) { var x = A[i] && isNum(A[i][j]) ? A[i][j] : (old && old[i] && isNum(old[i][j]) ? old[i][j] : 0); var q = snap(c, x); row.push(q == null ? 0 : q); } out.push(row); }
      return out;
    }
    return v;
  }
  function setControl(id, v, opt) {
    var c = CTL[id]; if (!c) return;
    state[id] = sanitize(c, v, state[id]);
    for (var k in CTL) {
      var d = CTL[k];
      if (k !== id && (d.length === id || d.rows === id || d.cols === id)) { state[k] = sanitize(d, state[k], state[k]); buildCtl(d); }
    }
    syncCtl(id);
    if (!(opt && opt.quiet)) scheduleUpdate();
  }
  function setItem(id, i, v) {
    var c = CTL[id]; if (!c) return;
    var arr = state[id].slice();
    if (c.type === 'simplex') { setControl(id, simplexSet(arr, i, snap(c, v))); return; }
    arr[i] = v; setControl(id, arr);
  }
  function setCell(id, i, j, v) { var A = clone(state[id]); if (!A[i]) return; A[i][j] = v; setControl(id, A); }
  function simplexSet(arr, i, h) {
    var n = arr.length; if (n === 1) return [1];
    h = clamp(Number(h), 0, 1);
    var rest = 0; arr.forEach(function (v, j) { if (j !== i) rest += v; });
    var out = arr.slice(), remain = 1 - h; out[i] = h;
    arr.forEach(function (v, j) { if (j !== i) out[j] = rest > 1e-12 ? v * remain / rest : remain / (n - 1); });
    return out;
  }
  function bindGet(b) {
    if (!b) return null;
    if (typeof b === 'string') { var v = state[b]; return Array.isArray(v) ? [v[0], v[1]] : null; }
    if (Array.isArray(b)) return [state[b[0]], state[b[1]]];
    if (b.id && state[b.id]) {
      var m = state[b.id];
      if (b.row != null && m[b.row]) return [m[b.row][0], m[b.row][1]];
      if (b.col != null) return [m[0][b.col], m[1][b.col]];
    }
    return null;
  }
  function bindSet(b, xy) {
    if (typeof b === 'string') { var v = state[b].slice(); v[0] = xy[0]; v[1] = xy[1]; setControl(b, v); }
    else if (Array.isArray(b)) { setControl(b[0], xy[0], { quiet: true }); setControl(b[1], xy[1]); }
    else if (b && b.id) {
      var A = clone(state[b.id]);
      if (b.row != null) { A[b.row][0] = xy[0]; A[b.row][1] = xy[1]; }
      else if (b.col != null) { A[0][b.col] = xy[0]; A[1][b.col] = xy[1]; }
      setControl(b.id, A);
    }
  }

  function fmtIn(v, step) { return isNum(v) ? (step ? v.toFixed(Math.min(10, decimalsOf(step))) : String(v)) : ''; }
  function scrubbable(inp, getStep, onVal) {
    var sx = 0, sy = 0, sv = 0, moved = false, pid = null;
    inp.addEventListener('mousedown', function (e) { if (document.activeElement !== inp) e.preventDefault(); });
    inp.addEventListener('pointerdown', function (e) {
      if (document.activeElement === inp || e.button !== 0) return;
      sx = e.clientX; sy = e.clientY; sv = parseFloat(inp.value) || 0; moved = false; pid = e.pointerId;
      e.preventDefault(); try { inp.setPointerCapture(pid); } catch (_) { /* ignore */ }
    });
    inp.addEventListener('pointermove', function (e) {
      if (pid === null) return;
      var d = (e.clientX - sx) - (e.clientY - sy);
      if (!moved && Math.abs(d) < 3) return;
      if (!moved) { moved = true; FAST = true; DRAG = true; document.body.classList.add('dragging'); }
      onVal(sv + Math.round(d / 4) * getStep());
    });
    var end = function () {
      if (pid === null) return;
      try { inp.releasePointerCapture(pid); } catch (_) { /* ignore */ }
      pid = null;
      if (moved) { FAST = false; DRAG = false; document.body.classList.remove('dragging'); scheduleUpdate(); }
      else { inp.focus(); inp.select(); }
    };
    inp.addEventListener('pointerup', end); inp.addEventListener('pointercancel', end);
  }
  function itemLabel(c, i) {
    if (c.labels && c.labels[i] != null) return md(c.labels[i]);
    if (c.sym) return symHTML((symKey(c.sym) || c.sym).split(/[_^]/)[0] + '_' + (i + 1));
    return String(i + 1);
  }
  function buildCtl(c) {
    var box = CTLDOM[c.id];
    if (!box) { box = CTLDOM[c.id] = el('div', 'ctl'); $('#controls').appendChild(box); }
    var color = col(c.color || c.sym, PALETTE.blue), uid = 'ctl-' + c.id.replace(/[^\w-]/g, '_');
    box.style.setProperty('--c', color);
    if (c.sym) box.dataset.sym = symKey(c.sym) || c.sym;
    var label = md(c.label || c.id), help = c.help ? '<div class="ctl-help">' + md(c.help) + '</div>' : '';
    var t = c.type;
    if (t === 'slider' || t === 'play') {
      box.innerHTML = '<div class="ctl-h"><label for="' + uid + '">' + label + '</label><input type="number" class="num" aria-label="' + esc(plain(c.label || c.id)) + ' (value)" min="' + c.min + '" max="' + c.max + '" step="' + c.step + '"></div>' +
        (t === 'play' ? '<div class="play-row"><button type="button" class="playbtn" aria-label="Play">&#9654;</button><input type="range" id="' + uid + '"></div>' : '<input type="range" id="' + uid + '">') + help;
      var rng = box.querySelector('input[type=range]'), nb = box.querySelector('.num');
      rng.min = c.min; rng.max = c.max; rng.step = c.step;
      rng.addEventListener('input', function () { setControl(c.id, +rng.value); });
      rng.addEventListener('pointerdown', function () { FAST = true; });
      rng.addEventListener('pointerup', function () { FAST = false; });
      nb.addEventListener('change', function () { setControl(c.id, nb.value); syncCtl(c.id, true); });
      nb.addEventListener('input', function () { var v = Number(nb.value); if (nb.value !== '' && isNum(v) && v >= c.min && v <= c.max) setControl(c.id, v); });
      scrubbable(nb, function () { return c.step; }, function (v) { setControl(c.id, v); syncCtl(c.id, true); });
      if (t === 'play') {
        var btn = box.querySelector('.playbtn');
        btn.addEventListener('click', function () {
          if (box._timer) { stopPlay(box, btn); return; }
          if (state[c.id] >= c.max - 1e-12) setControl(c.id, c.min);
          btn.innerHTML = '&#10074;&#10074;'; btn.setAttribute('aria-label', 'Pause');
          box._timer = setInterval(function () {
            var v = state[c.id] + c.step;
            if (v > c.max + 1e-9) { if (c.loop) v = c.min; else { stopPlay(box, btn); return; } }
            setControl(c.id, v);
          }, c.interval || Math.round(1000 / (c.speed || 4)));
        });
      }
      box._sync = function (force) {
        var v = state[c.id];
        rng.value = v; rng.style.setProperty('--p', ((v - c.min) / (c.max - c.min) * 100) + '%');
        if (force || document.activeElement !== nb) nb.value = fmtIn(v, c.step);
      };
    } else if (t === 'toggle') {
      box.innerHTML = '<label class="switch"><input type="checkbox" id="' + uid + '"><span>' + label + '</span></label>' + help;
      var cb = box.querySelector('input');
      cb.addEventListener('change', function () { setControl(c.id, cb.checked); });
      box._sync = function () { cb.checked = !!state[c.id]; };
    } else if (t === 'select') {
      box.innerHTML = '<div class="ctl-h"><span class="lb" id="' + uid + '-l">' + label + '</span></div><div class="seg" role="radiogroup" aria-labelledby="' + uid + '-l">' +
        c.options.map(function (op, i) { return '<label><input type="radio" name="' + uid + '" value="' + i + '"><span>' + md(op.label) + '</span></label>'; }).join('') + '</div>' + help;
      var radios = box.querySelectorAll('input');
      radios.forEach(function (r) { r.addEventListener('change', function () { if (r.checked) setControl(c.id, c.options[+r.value].value); }); });
      box._sync = function () { radios.forEach(function (r) { r.checked = c.options[+r.value].value === state[c.id]; }); };
    } else if (t === 'vector' || t === 'simplex') {
      var arr = state[c.id], rows = '';
      for (var i = 0; i < arr.length; i++) rows += '<div class="vrow"><span class="vl">' + itemLabel(c, i) + '</span><input type="range" min="' + c.min + '" max="' + c.max + '" step="' + (t === 'simplex' ? 0.01 : c.step) + '" aria-label="' + esc(plain(c.label || c.id)) + ' item ' + (i + 1) + '"><input type="number" class="num" step="' + (t === 'simplex' ? 0.01 : c.step) + '" min="' + c.min + '" max="' + c.max + '" aria-label="' + esc(plain(c.label || c.id)) + ' item ' + (i + 1) + ' (value)"></div>';
      box.innerHTML = '<div class="ctl-h"><span class="lb">' + label + '</span></div>' + rows + (t === 'simplex' ? '<div class="vsum"></div>' : '') + help;
      var vr = box.querySelectorAll('.vrow');
      vr.forEach(function (row, i2) {
        var r = row.querySelector('input[type=range]'), nbx = row.querySelector('.num');
        r.addEventListener('input', function () { setItem(c.id, i2, +r.value); });
        r.addEventListener('pointerdown', function () { FAST = true; });
        r.addEventListener('pointerup', function () { FAST = false; });
        nbx.addEventListener('change', function () { if (nbx.value !== '') setItem(c.id, i2, +nbx.value); syncCtl(c.id, true); });
        scrubbable(nbx, function () { return t === 'simplex' ? 0.01 : c.step; }, function (v) { setItem(c.id, i2, v); syncCtl(c.id, true); });
      });
      box._sync = function (force) {
        var a = state[c.id];
        vr.forEach(function (row, i3) {
          var r = row.querySelector('input[type=range]'), nbx = row.querySelector('.num');
          r.value = a[i3]; r.style.setProperty('--p', ((a[i3] - c.min) / (c.max - c.min) * 100) + '%');
          if (force || document.activeElement !== nbx) nbx.value = fmtIn(a[i3], t === 'simplex' ? 0.001 : c.step);
        });
        var sm = box.querySelector('.vsum'); if (sm) sm.textContent = 'sum = ' + fmt(M.sum(a), 3);
      };
    } else if (t === 'matrix') {
      var A = state[c.id], R = A.length, C = A[0] ? A[0].length : 0;
      var cells = '';
      for (var ri = 0; ri < R; ri++) for (var ci = 0; ci < C; ci++) cells += '<input type="number" class="num" data-i="' + ri + '" data-j="' + ci + '" step="' + c.step + '" min="' + c.min + '" max="' + c.max + '" aria-label="' + esc(plain(c.label || c.id)) + ' row ' + (ri + 1) + ' column ' + (ci + 1) + '">';
      var rl = c.rowLabels ? '<div class="mtx-rows">' + A.map(function (_, i4) { return '<span>' + md(labelAt(c.rowLabels, i4, '')) + '</span>'; }).join('') + '</div>' : '';
      box.innerHTML = '<div class="ctl-h"><span class="lb">' + label + '</span></div><div class="mtx-wrap">' + rl + '<div class="mtx" style="grid-template-columns:repeat(' + C + ',52px)">' + cells + '</div></div>' + help;
      var ins = box.querySelectorAll('.mtx input');
      ins.forEach(function (inp) {
        var i5 = +inp.dataset.i, j5 = +inp.dataset.j;
        inp.addEventListener('change', function () { if (inp.value !== '') setCell(c.id, i5, j5, +inp.value); syncCtl(c.id, true); });
        inp.addEventListener('input', function () { var v = Number(inp.value); if (inp.value !== '' && isNum(v) && v >= c.min && v <= c.max) setCell(c.id, i5, j5, v); });
        scrubbable(inp, function () { return c.step; }, function (v) { setCell(c.id, i5, j5, v); syncCtl(c.id, true); });
      });
      box._sync = function (force) {
        var B = state[c.id];
        ins.forEach(function (inp) { if (force || document.activeElement !== inp) inp.value = fmtIn(B[+inp.dataset.i][+inp.dataset.j], c.step); });
      };
    }
    box._sync(true);
  }
  function stopPlay(box, btn) { clearInterval(box._timer); box._timer = null; btn.innerHTML = '&#9654;'; btn.setAttribute('aria-label', 'Play'); }
  function syncCtl(id, force) { var b = CTLDOM[id]; if (b && b._sync) b._sync(force); }

  // ================================================================== update loop
  var pending = false;
  function scheduleUpdate() { if (pending) return; pending = true; requestAnimationFrame(function () { pending = false; update(); }); }
  function note(where, msg) { ERRORS.push(where + ': ' + msg); }
  function update() {
    ERRORS = [];
    var errBox = $('#errors');
    if (!computeFn || !renderFn) {
      errBox.innerHTML = '<div class="errbox">The generated ' + (!computeFn ? 'calculation' : 'drawing') + ' code could not be loaded, so the live visual is unavailable. The explanation below still applies.</div>';
      runChecks(); return;
    }
    try { result = computeFn(clone(state)); }
    catch (e) { errBox.innerHTML = '<div class="errbox">These inputs could not be computed: <code>' + esc(e.message || e) + '</code>. Try other values or press Reset.</div>'; runChecks(); return; }
    try { renderFn(state, result, kit); pruneSlots(); }
    catch (e) { slotUse.clear(); note('render', e.message || String(e)); }
    errBox.innerHTML = ERRORS.length ? '<div class="errbox">' + ERRORS.map(esc).join('<br>') + '</div>' : '';
    runChecks();
    if (ACTIVE) applyLinks();
  }
  function runChecks() {
    var ul = $('#checklist'); if (!ul) return;
    if (!CHECKS.length) { $('#checks').style.display = 'none'; return; }
    ul.innerHTML = CHECKS.map(function (ck) {
      var ok = false, shown = '';
      try { ok = !!ck.test(state, result); shown = ck.show ? String(ck.show(state, result)) : ''; }
      catch (e) { ok = false; shown = 'could not evaluate: ' + (e.message || e); }
      return '<li><span class="' + (ok ? 'ok' : 'bad') + '">' + (ok ? '&#10003;' : '&#10007;') + '</span><span>' + md(ck.label) + (shown ? '<span class="cv">' + esc(shown) + '</span>' : '') + '</span></li>';
    }).join('');
  }

  // ================================================================== scripted animation (explorations / reset)
  var animToken = 0;
  function isNumericCtl(c) { return c.type === 'slider' || c.type === 'play' || c.type === 'vector' || c.type === 'simplex' || c.type === 'matrix'; }
  function animateTo(target, ms) {
    var my = ++animToken;
    var keys = Object.keys(target || {}).filter(function (k) { return CTL[k]; });
    // 1) snap discrete controls and anything that changes array shapes (e.g. number of outcomes)
    keys.forEach(function (k) {
      var c = CTL[k];
      var isDep = Object.keys(CTL).some(function (o2) { var d = CTL[o2]; return d.length === k || d.rows === k || d.cols === k; });
      if (!isNumericCtl(c) || isDep) setControl(k, target[k], { quiet: true });
    });
    var start = {}, goal = {};
    keys.forEach(function (k) {
      var c = CTL[k]; if (!isNumericCtl(c)) return;
      var g = sanitize(c, clone(target[k]), state[k]), s0 = clone(state[k]);
      var same = JSON.stringify(shapeOf(g)) === JSON.stringify(shapeOf(s0));
      if (!same) { state[k] = g; syncCtl(k, true); return; }
      start[k] = s0; goal[k] = g;
    });
    if (REDUCED || !Object.keys(goal).length) { Object.keys(goal).forEach(function (k) { state[k] = goal[k]; syncCtl(k, true); }); update(); return Promise.resolve(); }
    FAST = true;
    return new Promise(function (resolve) {
      var t0 = performance.now();
      var frameFn = function (now) {
        if (my !== animToken) { FAST = false; resolve(); return; }
        var t = Math.min(1, (now - t0) / ms), e = ease(t);
        Object.keys(goal).forEach(function (k) {
          var c = CTL[k], v = t < 1 ? deepLerp(start[k], goal[k], e) : goal[k];
          if (t < 1 && (c.type === 'slider' || c.type === 'play')) v = snap(c, v);
          state[k] = v; syncCtl(k, true);
        });
        update();
        if (t < 1) requestAnimationFrame(frameFn); else { FAST = false; update(); resolve(); }
      };
      requestAnimationFrame(frameFn);
    });
  }
  function shapeOf(v) { return Array.isArray(v) ? [v.length, Array.isArray(v[0]) ? v[0].length : 0] : 0; }
  function deepLerp(a, b, e) { if (Array.isArray(b)) return b.map(function (bv, i) { return deepLerp(a[i], bv, e); }); return a + (b - a) * e; }

  // ================================================================== page assembly
  function normData(D) {
    D = D || {};
    var hook = D.hook;
    if (hook && typeof hook === 'object') { D.why = D.why || hook.why; hook = hook.question || hook.text; }
    D.hook = hook;
    D.symbols = asArray(D.symbols).map(function (s) { return { key: String(s.key || s.sym || s.symbol || s.name || ''), meaning: s.meaning || s.desc || '', color: s.color }; }).filter(function (s) { return s.key; });
    D.scenes = asArray(D.scenes).length ? asArray(D.scenes) : [{ id: 's1', title: '', caption: '' }];
    D.scenes = D.scenes.map(function (sc, i) { return { id: String(sc.id || 's' + (i + 1)), title: sc.title || '', caption: sc.caption || sc.text || '', pause: sc.pause || sc.ponder || '', gate: sc.gate }; });
    D.explorations = asArray(D.explorations);
    D.grounding = D.grounding || {};
    return D;
  }
  kit.boot = function (data, compute, render, checks) {
    DATA = normData(data); computeFn = compute; renderFn = render; CHECKS = asArray(checks).filter(function (c) { return c && typeof c.test === 'function'; });
    tipEl = $('#tip');
    var used = {};
    DATA.symbols.forEach(function (s, i) {
      var c = s.color && PALETTE[s.color] ? s.color : null;
      if (!c || used[c]) c = SERIES.filter(function (n) { return !used[n]; })[0] || SERIES[i % SERIES.length];
      used[c] = 1; SYM[s.key] = { color: PALETTE[c], meaning: s.meaning };
    });
    var G = DATA.grounding;
    document.title = plain(DATA.title || 'Interactive explanation');
    $('#kicker').innerHTML = '<span class="dot"></span>Interactive explainer' + (G.paper ? ' · ' + esc(shortPaper(G.paper)) : '') + (G.section ? ' · ' + esc(G.section) : '');
    $('#title').innerHTML = md(DATA.title || '');
    $('#hook').innerHTML = md(DATA.hook || '');
    $('#why').innerHTML = md(DATA.why || '');
    $('#cast').innerHTML = DATA.symbols.map(function (s) { return '<span class="chip" data-sym="' + esc(s.key) + '" style="--c:' + SYM[s.key].color + '">' + symHTML(s.key) + '<span>' + md(s.meaning) + '</span></span>'; }).join('');
    // scenes
    var sc = $('#scenes'), multi = DATA.scenes.length > 1;
    sc.className = 'scenes ' + (multi ? 'walkthrough' : 'explorer');
    sc.innerHTML = DATA.scenes.map(function (s, i) {
      return '<section class="scene" id="scene-' + esc(s.id) + '"><div class="narr"><div class="scene-head">' + (multi ? '<div class="scene-n">' + (i + 1) + '</div>' : '') +
        '<div><h3>' + md(s.title) + '</h3><p class="caption">' + md(s.caption) + '</p></div></div></div><div class="viz" id="viz-' + esc(s.id) + '"></div></section>';
    }).join('');
    $('#rail').innerHTML = multi ? DATA.scenes.map(function (s, i) { return '<a href="#scene-' + esc(s.id) + '"><span class="n">' + (i + 1) + '</span>' + md(s.title) + '</a>'; }).join('') : '';
    // the general rule
    $('#eq').innerHTML = md(DATA.equation || '');
    $('#eq-words').innerHTML = md(DATA.equation_words || DATA.equationWords || '');
    $('#symtab').innerHTML = DATA.symbols.map(function (s) { return '<div data-sym="' + esc(s.key) + '" style="--c:' + SYM[s.key].color + '">' + symHTML(s.key) + '<span>' + md(s.meaning) + '</span></div>'; }).join('');
    if (!DATA.equation) $('#rule').style.display = 'none';
    // explorations
    $('#ex-grid').innerHTML = DATA.explorations.map(function (ex, i) {
      return '<article class="ex" data-i="' + i + '"><div class="ex-top"><span class="ex-n">' + (i + 1) + '</span><h3>' + md(ex.title || 'Exploration ' + (i + 1)) + '</h3></div>' +
        (ex.predict ? '<p><span class="tag pr">Predict</span>' + md(ex.predict) + '</p>' : '') +
        '<p><span class="tag do">Change</span>' + md(ex.change || ex['do'] || describePreset(ex.preset)) + '</p>' +
        '<div class="ex-btns"><button class="btn" type="button" data-act="try">&#9654; Try it</button><button class="btn ghost" type="button" data-act="reset">&#8634; Reset</button></div>' +
        '<div class="ex-reveal veiled"><p><span class="tag ob">What you see</span>' + md(ex.observe || '') + '</p><p><span class="tag wy">Why</span>' + md(ex.why || '') + '</p></div></article>';
    }).join('');
    if (!DATA.explorations.length) $('#explore').style.display = 'none';
    document.querySelectorAll('.ex').forEach(function (card) {
      var ex = DATA.explorations[+card.dataset.i];
      card.querySelector('[data-act=try]').addEventListener('click', function () { runExploration(ex, +card.dataset.i, card); });
      card.querySelector('[data-act=reset]').addEventListener('click', function () { closeNarrator(); animateTo(DEFAULTS, 700); });
    });
    // insights & sources
    if (DATA.takeaway) $('#takeaway').innerHTML = md(DATA.takeaway); else $('#takeaway-box').style.display = 'none';
    var mis = DATA.misconception || DATA.limitation;
    if (mis) $('#misconception').innerHTML = md(mis); else $('#misc-box').style.display = 'none';
    $('#cite').innerHTML = [G.paper ? '<b>' + md(G.paper) + '</b>' : '', G.section ? md(G.section) : '', G.equation ? md(G.equation) : ''].filter(Boolean).join(' &#183; ') +
      (DATA.source_url ? '<br><span class="src">' + esc(DATA.source_url) + '</span>' : '');
    $('#from-paper').innerHTML = asArray(G.from_paper || G.supported).map(function (t) { return '<li>' + md(t) + '</li>'; }).join('');
    $('#ours').innerHTML = asArray(G.simplifications || G.ours).map(function (t) { return '<li>' + md(t) + '</li>'; }).join('');
    // controls
    asArray(DATA.controls).forEach(function (raw) { var c = normCtl(raw); CTL[c.id] = c; });
    Object.keys(CTL).forEach(function (k) { state[k] = clone(CTL[k].value); });
    Object.keys(CTL).forEach(function (k) { state[k] = sanitize(CTL[k], state[k], state[k]); });
    Object.keys(CTL).forEach(function (k) { state[k] = sanitize(CTL[k], state[k], state[k]); DEFAULTS[k] = clone(state[k]); });
    if (!Object.keys(CTL).length) $('#controls').innerHTML = '<p class="ctl-help">No inputs for this page.</p>';
    Object.keys(CTL).forEach(function (k) { buildCtl(CTL[k]); });
    $('#reset').addEventListener('click', function () { closeNarrator(); animateTo(DEFAULTS, 700); });
    buildStages();
    document.querySelectorAll('#rail a').forEach(function (a) {
      a.addEventListener('click', function (e) {
        var k = stageOfScene(a.getAttribute('href').replace('#scene-', ''));
        if (!ALL && k > CUR) { e.preventDefault(); unlockTo(k, true); }
      });
    });
    wirePage();
    update();
    requestAnimationFrame(function () { update(); });
  };
  function shortPaper(p) { var s = plain(p); return s.length > 60 ? s.slice(0, 57) + '…' : s; }
  function describePreset(p) {
    if (!p) return '';
    return 'Set ' + Object.keys(p).map(function (k) {
      var c = CTL[k], v = p[k], name = c ? plain(c.label || k) : k;
      var vs = Array.isArray(v) ? (Array.isArray(v[0]) ? '[' + v.map(function (r) { return '[' + r.map(function (x) { return fmt(x); }).join(', ') + ']'; }).join(', ') + ']' : '[' + v.map(function (x) { return fmt(x); }).join(', ') + ']') : fmt(v);
      return name + ' = ' + vs;
    }).join('; ') + '.';
  }
  async function runExploration(ex, i, card) {
    var focus = ex.focus ? document.getElementById('scene-' + ex.focus) : document.querySelector('.scene');
    var fk = stageOfScene(ex.focus);
    if (fk > CUR && !ALL) unlockTo(fk, false);
    showNarrator(ex, i, false);
    if (focus) {
      var r = focus.getBoundingClientRect();
      if (r.top < 0 || r.top > innerHeight * 0.45) { focus.scrollIntoView({ behavior: REDUCED ? 'auto' : 'smooth', block: 'start' }); await sleep(REDUCED ? 0 : 650); }
    }
    await animateTo(ex.preset || {}, 1300);
    if (focus) { focus.classList.remove('focus'); void focus.offsetWidth; focus.classList.add('focus'); }
    card.querySelector('.ex-reveal').classList.remove('veiled');
    showNarrator(ex, i, true);
  }
  function showNarrator(ex, i, done) {
    var n = $('#narrator');
    n.innerHTML = '<button class="nx" type="button" aria-label="Close">&times;</button><div class="nt">Exploration ' + (i + 1) + (done ? '' : ' · watch the visuals') + '</div><h4>' + md(ex.title || '') + '</h4>' +
      (done ? '<p><span class="tag ob">What you see</span>' + md(ex.observe || '') + '</p><p><span class="tag wy">Why</span>' + md(ex.why || '') + '</p>'
        : '<p><span class="tag pr">Predict</span>' + md(ex.predict || 'What do you expect to happen?') + '</p>');
    n.classList.add('on');
    n.querySelector('.nx').addEventListener('click', closeNarrator);
  }
  function closeNarrator() { $('#narrator').classList.remove('on'); }
  function wirePage() {
    // symbol hover: tokens, chips, rows, controls and component frames sharing a symbol light up together
    document.addEventListener('pointerover', function (e) {
      var t = e.target.closest && e.target.closest('.sym, .chip, .symtab > div');
      if (!t || DRAG) return;
      var key = t.dataset.sym || (t.querySelector('.sym') && t.querySelector('.sym').dataset.sym);
      if (!key) return;
      symHighlight(key, true);
      if (t.classList.contains('sym') && SYM[key] && SYM[key].meaning) showTip(symHTML(key) + ' &nbsp;' + md(SYM[key].meaning), e);
      var out = function () { symHighlight(key, false); hideTip(); t.removeEventListener('pointerleave', out); };
      t.addEventListener('pointerleave', out);
    });
    var prog = $('#progress');
    var onScroll = function () { var h = document.documentElement; prog.style.width = (h.scrollTop / Math.max(1, h.scrollHeight - h.clientHeight) * 100) + '%'; };
    addEventListener('scroll', onScroll, { passive: true }); onScroll();
    var lastW = innerWidth, rt = 0;
    addEventListener('resize', function () {
      clearTimeout(rt);
      rt = setTimeout(function () { if (Math.abs(innerWidth - lastW) < 4) return; lastW = innerWidth; document.querySelectorAll('.viz').forEach(function (v) { v.textContent = ''; }); update(); }, 160);
    });
    addEventListener('keydown', function (e) { if (e.key === 'Escape') closeNarrator(); });
    document.addEventListener('pointerup', function () { if (!DRAG) FAST = false; });
  }

  // ================================================================== progressive reveal: one idea at a time
  // Stages = groups of scenes (a scene with gate:false joins the previous one), then the general rule,
  // the explorations, and the wrap-up. Later stages stay collapsed until the learner presses Continue.
  // Collapsed content stays in the DOM (readable text, working sidebar); "Show everything" opens all.
  var STAGES = [], CUR = 0, ALL = false, pill = null;
  function stageOfScene(id) {
    for (var k = 0; k < STAGES.length; k++) if (STAGES[k].scenes.indexOf(String(id)) >= 0) return k;
    return -1;
  }
  function buildStages() {
    STAGES = [];
    DATA.scenes.forEach(function (sc, i) {
      var node = document.getElementById('scene-' + sc.id); if (!node) return;
      if (!STAGES.length || (i > 0 && sc.gate !== false)) STAGES.push({ els: [], scenes: [], ctls: [], num: i + 1, title: sc.title });
      var st = STAGES[STAGES.length - 1];
      st.els.push(node); st.scenes.push(sc.id); st.pause = sc.pause;
    });
    var tail = [[['#rule'], 'The general rule'], [['#explore'], 'Try it yourself: two guided explorations'], [['#insights', '#sources'], 'The key idea, a limitation, and the sources']];
    tail.forEach(function (t) {
      var els = t[0].map(function (q) { return $(q); }).filter(function (n) { return n && n.style.display !== 'none'; });
      if (els.length) STAGES.push({ els: els, scenes: [], ctls: [], title: t[1], pause: '' });
    });
    Object.keys(CTL).forEach(function (id) {
      var k = CTL[id].scene != null ? stageOfScene(CTL[id].scene) : 0;
      if (k > 0) STAGES[k].ctls.push(CTLDOM[id]);
    });
    STAGES.forEach(function (st, k) {
      if (k === STAGES.length - 1) return;
      var nx = STAGES[k + 1], g = el('div', 'gate');
      g.innerHTML = (st.pause ? '<div class="ponder"><div class="eyebrow">Pause and ponder</div><p>' + md(st.pause) + '</p></div>' : '') +
        '<button class="btn gate-btn" type="button"><span>Continue</span><span class="nx">' + (nx.num ? '<b>' + nx.num + '.</b> ' : '') + md(nx.title) + '</span><span aria-hidden="true">&#8595;</span></button>';
      var last = st.els[st.els.length - 1];
      last.parentNode.insertBefore(g, last.nextSibling);
      g.querySelector('button').addEventListener('click', function () { unlockTo(k + 1, true); });
      st.gate = g;
    });
    pill = el('button', 'guide-pill', document.body); pill.type = 'button';
    pill.addEventListener('click', function () { ALL = !ALL; applyStages(); scheduleUpdate(); });
    if (/all/i.test(location.hash)) ALL = true;
    var m = location.hash.match(/^#scene-(.+)$/);
    if (m && stageOfScene(m[1]) > 0) CUR = stageOfScene(m[1]);
    applyStages();
  }
  function applyStages() {
    STAGES.forEach(function (st, k) {
      var open = ALL || k <= CUR;
      st.els.forEach(function (e) { e.classList.toggle('locked', !open); });
      st.ctls.forEach(function (b) { if (b) b.classList.toggle('locked', !open); });
      if (st.gate) st.gate.classList.toggle('locked', ALL || k !== CUR);
    });
    document.querySelectorAll('#rail a').forEach(function (a) {
      a.classList.toggle('lockd', !ALL && stageOfScene(a.getAttribute('href').replace('#scene-', '')) > CUR);
    });
    if (pill) {
      pill.innerHTML = ALL ? '&#9654; Step by step' : 'Show everything';
      pill.setAttribute('aria-pressed', ALL ? 'true' : 'false');
      pill.style.display = STAGES.length > 1 ? '' : 'none';
    }
  }
  function unlockTo(k, scroll) {
    k = Math.min(k, STAGES.length - 1);
    if (k < 0) return;
    var from = CUR;
    if (k > CUR) {
      CUR = k; applyStages();
      for (var j = from + 1; j <= CUR; j++) {
        STAGES[j].els.forEach(function (e) {
          e.querySelectorAll('.viz').forEach(function (v) { v.textContent = ''; });   // replay the creation animations
          e.classList.remove('revealing'); void e.offsetWidth; e.classList.add('revealing');
        });
        STAGES[j].ctls.forEach(function (b) { if (b) { b.classList.remove('fresh'); void b.offsetWidth; b.classList.add('fresh'); } });
      }
      scheduleUpdate();
    }
    if (scroll) { var tgt = STAGES[k].els[0]; setTimeout(function () { tgt.scrollIntoView({ behavior: REDUCED ? 'auto' : 'smooth', block: 'start' }); }, 40); }
  }

  // public API used by generated render() code
  kit.text = kit.note;
  kit.color = function (c) { return col(c); };
  kit.fmt = fmt;
  kit.sub = M.subDigits;
  kit.palette = PALETTE;
  window.kit = kit;
  window.P2P = { state: state, setControl: setControl, errors: function () { return ERRORS.slice(); }, result: function () { return result; } };
})();
