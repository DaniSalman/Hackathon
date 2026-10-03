/* mathlib.js — small, dependency-free math helpers shared by the page and the QuickJS checks.
   Exposes a single global `M`. Generic: nothing here is specific to any paper. */
var M = (function () {
  'use strict';
  var isNum = function (v) { return typeof v === 'number' && isFinite(v); };
  var sum = function (a) { var s = 0; for (var i = 0; i < a.length; i++) s += a[i]; return s; };
  var mean = function (a) { return a.length ? sum(a) / a.length : NaN; };
  var max = function (a) { return Math.max.apply(null, a); };
  var min = function (a) { return Math.min.apply(null, a); };
  var argmax = function (a) { var b = 0; for (var i = 1; i < a.length; i++) if (a[i] > a[b]) b = i; return b; };
  var argmin = function (a) { var b = 0; for (var i = 1; i < a.length; i++) if (a[i] < a[b]) b = i; return b; };
  var range = function (n, start) { start = start || 0; var r = []; for (var i = 0; i < n; i++) r.push(start + i); return r; };
  var linspace = function (a, b, n) {
    if (n <= 1) return [a];
    var r = []; for (var i = 0; i < n; i++) r.push(a + (b - a) * i / (n - 1)); return r;
  };
  var zeros = function (r, c) {
    if (c === undefined) return range(r).map(function () { return 0; });
    return range(r).map(function () { return range(c).map(function () { return 0; }); });
  };
  var dot = function (a, b) { var s = 0; for (var i = 0; i < a.length; i++) s += a[i] * b[i]; return s; };
  var transpose = function (A) { return A[0].map(function (_, j) { return A.map(function (r) { return r[j]; }); }); };
  var matmul = function (A, B) {
    return A.map(function (r) { return B[0].map(function (_, j) { var s = 0; for (var k = 0; k < r.length; k++) s += r[k] * B[k][j]; return s; }); });
  };
  var matvec = function (A, x) { return A.map(function (r) { return dot(r, x); }); };
  var map2 = function (A, f) { return A.map(function (r, i) { return r.map(function (v, j) { return f(v, i, j); }); }); };
  var scale = function (A, k) { return Array.isArray(A[0]) ? map2(A, function (v) { return v * k; }) : A.map(function (v) { return v * k; }); };
  var add = function (A, B) { return Array.isArray(A[0]) ? map2(A, function (v, i, j) { return v + B[i][j]; }) : A.map(function (v, i) { return v + B[i]; }); };
  var sub = function (A, B) { return Array.isArray(A[0]) ? map2(A, function (v, i, j) { return v - B[i][j]; }) : A.map(function (v, i) { return v - B[i]; }); };
  var outer = function (a, b) { return a.map(function (x) { return b.map(function (y) { return x * y; }); }); };
  var rowSums = function (A) { return A.map(sum); };
  var colSums = function (A) { return transpose(A).map(sum); };
  var cumsum = function (a) { var s = 0; return a.map(function (v) { s += v; return s; }); };
  var norm = function (v) { return Math.sqrt(dot(v, v)); };
  var cosine = function (a, b) { var d = norm(a) * norm(b); return d ? dot(a, b) / d : 0; };
  var clamp = function (x, a, b) { return Math.min(b, Math.max(a, x)); };
  var round = function (x, d) { var k = Math.pow(10, d || 0); return Math.round(x * k) / k; };
  /* Numerically stable softmax (subtracts the max before exponentiating). T = temperature. */
  var softmax = function (v, T) {
    T = T || 1; var m = -Infinity, i;
    for (i = 0; i < v.length; i++) if (v[i] / T > m) m = v[i] / T;
    var e = v.map(function (x) { return Math.exp(x / T - m); }), s = sum(e);
    return e.map(function (x) { return x / s; });
  };
  var softmaxRows = function (A, T) { return A.map(function (r) { return softmax(r, T); }); };
  /* p * log2(p) with the convention 0 * log 0 = 0 (its limit as p -> 0). */
  var xlog2x = function (p) { return p > 0 ? p * Math.log2(p) : 0; };
  var xlnx = function (p) { return p > 0 ? p * Math.log(p) : 0; };
  /* Scale nonnegative weights to sum to 1; all-zero input becomes uniform. */
  var normalize = function (v) { var s = sum(v); return s > 0 ? v.map(function (x) { return x / s; }) : v.map(function () { return 1 / v.length; }); };
  var sigmoid = function (x) { return 1 / (1 + Math.exp(-x)); };
  var relu = function (x) { return Math.max(0, x); };
  /* Deep approximate equality for numbers / arrays / nested arrays. */
  var close = function (a, b, tol) {
    tol = tol == null ? 1e-9 : tol;
    if (Array.isArray(a) && Array.isArray(b)) {
      if (a.length !== b.length) return false;
      for (var i = 0; i < a.length; i++) if (!close(a[i], b[i], tol)) return false;
      return true;
    }
    if (typeof a === 'number' && typeof b === 'number') {
      if (a === b) return true;
      return Math.abs(a - b) <= tol * Math.max(1, Math.abs(a), Math.abs(b));
    }
    return a === b;
  };
  /* Display formatting: auto precision, '—' for NaN, ∞ for infinities, no '-0'. */
  var fmt = function (v, d) {
    if (typeof v === 'boolean') return v ? 'on' : 'off';
    if (typeof v !== 'number') return v == null ? '' : String(v);
    if (v !== v) return '—';
    if (v === Infinity) return '∞';
    if (v === -Infinity) return '-∞';
    if (d == null) {
      var a = Math.abs(v);
      if (Number.isInteger(v)) d = 0;
      else if (a !== 0 && a < 0.001) return v.toExponential(2);
      else d = a >= 1000 ? 0 : a >= 100 ? 1 : a >= 10 ? 2 : 3;
    }
    var s = v.toFixed(d);
    if (/^-0(\.0+)?$/.test(s)) s = s.slice(1);
    return s;
  };
  /* Unicode subscript digits: M.sub(12) -> '₁₂' (handy for labels like 'q' + M.sub(1)). */
  var subDigits = function (n) { return String(n).replace(/[0-9]/g, function (d) { return '₀₁₂₃₄₅₆₇₈₉'[+d]; }); };
  return {
    isNum: isNum, sum: sum, mean: mean, max: max, min: min, argmax: argmax, argmin: argmin, range: range,
    linspace: linspace, zeros: zeros, dot: dot, transpose: transpose, matmul: matmul, matvec: matvec,
    map2: map2, scale: scale, add: add, sub: sub, outer: outer, rowSums: rowSums, colSums: colSums,
    cumsum: cumsum, norm: norm, cosine: cosine, clamp: clamp, round: round, softmax: softmax,
    softmaxRows: softmaxRows, xlog2x: xlog2x, xlnx: xlnx, normalize: normalize, sigmoid: sigmoid,
    relu: relu, close: close, fmt: fmt, subDigits: subDigits
  };
})();
