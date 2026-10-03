"""Calculator for reviewer-written math checks.

The reviewer model never judges numbers itself. It writes one entry per numeric
claim: where the claim is, the formula from the paper, and any extra inputs. This
module evaluates each formula in a QuickJS sandbox and compares the result with
the generator's claim.

    passed     -> logged only
    failed     -> returned as generator-facing issues
    discarded  -> the entry itself was unusable (bad path, misquote, formula error);
                  logged only, never blamed on the generator

Helpers are written here, independently of the generator's mathlib.js, so a bug
shared by the page and the reference cannot hide a wrong number.
"""
import json
import math
import re
import quickjs

MAX_ENTRIES = 30
TEST_TOLERANCE = 1e-6
PINNED = re.compile(r'^(explorations|tests)\[\d+\]')  # these claims describe one exact state
IDENTIFIER = re.compile(r'^[A-Za-z_$][\w$]*$')
PATH_TOKEN = re.compile(r'([A-Za-z_][\w]*)|\[(\d+)\]')
NUMBER = re.compile(r'(?<![\w.^])[-−]?\d+(?:\.\d+)?(?!\w|\.\d)')

HELPERS = r'''
'use strict';
var sum=a=>a.reduce((s,x)=>s+x,0), mean=a=>sum(a)/a.length;
var max=a=>Math.max.apply(null,a), min=a=>Math.min.apply(null,a);
var dot=(a,b)=>{if(a.length!==b.length)throw Error('dot: length mismatch');return sum(a.map((x,i)=>x*b[i]))};
var transpose=A=>A[0].map((_,j)=>A.map(r=>r[j]));
var matmul=(A,B)=>A.map(r=>B[0].map((_,j)=>dot(r,B.map(b=>b[j]))));
var matvec=(A,x)=>A.map(r=>dot(r,x));
var softmax=v=>{var m=max(v),e=v.map(x=>Math.exp(x-m)),s=sum(e);return e.map(x=>x/s)};
var softmaxRows=A=>A.map(softmax);
var rowSums=A=>A.map(sum), norm=v=>Math.sqrt(dot(v,v));
var log2=Math.log2, ln=Math.log, exp=Math.exp, sqrt=Math.sqrt, abs=Math.abs, pow=Math.pow;
var xlog2x=p=>p>0?p*Math.log2(p):0, xlnx=p=>p>0?p*Math.log(p):0;
var range=n=>Array.from({length:n},(_,i)=>i), zeros=n=>range(n).map(()=>0);
'''
HELPER_NAMES = {'sum','mean','max','min','dot','transpose','matmul','matvec','softmax','softmaxRows',
                'rowSums','norm','log2','ln','exp','sqrt','abs','pow','xlog2x','xlnx','range','zeros','s','Math'}
RESERVED = {'break','case','catch','class','const','continue','debugger','default','delete','do','else','export',
            'extends','false','finally','for','function','if','import','in','instanceof','let','new','null','return',
            'super','switch','this','throw','true','try','typeof','var','void','while','with','yield','await'}
HELP_TEXT = ('sum mean max min dot transpose matmul matvec softmax softmaxRows rowSums norm '
             'log2 ln exp sqrt abs pow xlog2x xlnx (0·log 0 = 0) range zeros, plus Math.*')


class EntryError(ValueError):
    """The reviewer's entry cannot be evaluated; not the generator's fault."""


def resolve(path, content, controls, tests):
    tokens = [(name, int(index) if index else None) for name, index in PATH_TOKEN.findall(path)]
    if not tokens or ''.join(f'.{n}' if n else f'[{i}]' for n, i in tokens).lstrip('.') != path:
        raise EntryError(f'unreadable field path {path!r}')
    roots = {'tests': tests, 'controls': controls}
    value = roots.get(tokens[0][0], content) if tokens[0][0] in roots else content
    for position, (name, index) in enumerate(tokens):
        if position == 0 and name in roots:
            continue
        try:
            value = value[name] if name else value[index]
        except (KeyError, IndexError, TypeError):
            raise EntryError(f'field {path!r} does not exist in the reply') from None
    return value


def defaults(controls):
    state = {}
    for control in controls:
        if not isinstance(control, dict):
            continue
        value = control.get('value')
        if control.get('type') == 'select' and value is None and control.get('options'):
            option = control['options'][0]
            value = option.get('value') if isinstance(option, dict) else option
        state[str(control.get('id'))] = value
    return state


def page_state(path, content, controls, tests):
    """The state the page itself is in for this claim: defaults plus the preset or test state.

    Claims inside an exploration or test describe that exact state, so reviewer inputs may only
    add missing values there. Elsewhere (captions, why, ...) they may replace the defaults."""
    state = defaults(controls)
    match = re.match(r'^(explorations|tests)\[(\d+)\]', path)
    if match:
        owner = (content.get('explorations', []) if match.group(1) == 'explorations' else tests)
        index = int(match.group(2))
        if index < len(owner) and isinstance(owner[index], dict):
            state.update(owner[index].get('preset' if match.group(1) == 'explorations' else 'state') or {})
    return state


def evaluate(formula, state):
    names = [k for k in state if IDENTIFIER.match(k) and k not in HELPER_NAMES and k not in RESERVED]
    script = (HELPERS + 'var s=JSON.parse(' + json.dumps(json.dumps(state, allow_nan=False)) + ');\n' +
              ''.join(f'var {k}=s[{json.dumps(k)}];' for k in names) +
              '\nJSON.stringify((function(){return (\n' + formula + '\n);})());')
    context = quickjs.Context()
    context.set_memory_limit(16 * 1024 * 1024)
    context.set_time_limit(0.3)
    try:
        raw = context.eval(script)
    except Exception as exc:
        raise EntryError('formula failed: ' + (str(exc).splitlines()[0] if str(exc) else type(exc).__name__)) from None
    result = json.loads(raw) if isinstance(raw, str) else None
    if not finite(result):
        raise EntryError('formula did not return finite numbers')
    return result


def finite(value):
    if isinstance(value, list):
        return bool(value) and all(finite(v) for v in value)
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def same_shape(a, b):
    if isinstance(a, list) or isinstance(b, list):
        return isinstance(a, list) and isinstance(b, list) and len(a) == len(b) and all(same_shape(x, y) for x, y in zip(a, b))
    return True


def close(a, b, tol):
    if isinstance(a, list):
        return all(close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def written_tolerance(literal):
    """Half a unit in the last written digit: 0.998 -> 0.0005, 6.36 -> 0.005, 580 -> 5."""
    digits = literal.lstrip('-−')
    if '.' in digits:
        return 0.5 * 10 ** -len(digits.split('.')[1])
    zeros = len(digits) - len(digits.rstrip('0')) if digits.strip('0') else 0
    return 0.5 * 10 ** zeros


def text_claim(entry, field_text):
    quote, value = entry.get('quote'), entry.get('value')
    if not isinstance(field_text, str):
        raise EntryError('a text claim must point at a text field')
    if not isinstance(quote, str) or not quote.strip() or not finite(value) or isinstance(value, list):
        raise EntryError('a text claim needs quote and a numeric value')
    if ' '.join(quote.split()) not in ' '.join(field_text.split()):
        raise EntryError('quote does not appear in the field')
    literals = [m.group(0) for m in NUMBER.finditer(quote) if float(m.group(0).replace('−', '-')) == value]
    if not literals:
        raise EntryError(f'value {value} is not written in the quote')
    return value, written_tolerance(literals[0])


def fmt(value):
    if isinstance(value, list):
        return '[' + ', '.join(fmt(v) for v in value) + ']'
    return f'{value:.6g}'


def run(entries, content, controls, tests):
    """Evaluate reviewer entries against the reply. Returns {'passed','failed','discarded','issues'}."""
    out = {'passed': [], 'failed': [], 'discarded': [], 'issues': []}
    if not isinstance(entries, list):
        out['discarded'].append({'id': None, 'field': None, 'reason': 'calculations must be a list'})
        return out
    for position, entry in enumerate(entries):
        ident = entry.get('id') if isinstance(entry, dict) else None
        field = entry.get('field') if isinstance(entry, dict) else None
        try:
            if position >= MAX_ENTRIES:
                raise EntryError(f'more than {MAX_ENTRIES} entries')
            if not isinstance(entry, dict) or not all(isinstance(entry.get(k), str) and entry[k].strip() for k in ('id', 'field', 'source', 'formula')):
                raise EntryError('entry needs id, field, source and formula strings')
            inputs = entry.get('inputs', {})
            if not isinstance(inputs, dict):
                raise EntryError('inputs must be an object')
            target = resolve(field, content, controls, tests)
            state = page_state(field, content, controls, tests)
            overrides = sorted(k for k, v in inputs.items() if k in state and state[k] != v)
            if overrides and PINNED.match(field):
                raise EntryError('inputs contradict the preset/test state this claim describes: ' + ', '.join(overrides))
            state.update(inputs)
            if re.match(r'^tests\[\d+\]\.expect\.', field):
                if not finite(target):
                    raise EntryError('test expectation is not numeric')
                index = int(re.match(r'^tests\[(\d+)\]', field).group(1))
                tolerance = tests[index].get('tol', TEST_TOLERANCE)
                claimed, relative = target, True
                if not finite(tolerance) or isinstance(tolerance, list) or tolerance <= 0:
                    tolerance = TEST_TOLERANCE
            else:
                claimed, tolerance = text_claim(entry, target)
                relative = False
            computed = evaluate(entry['formula'], state)
            if not same_shape(computed, claimed):
                raise EntryError('formula result and claim have different shapes')
            ok = close(computed, claimed, tolerance) if relative else abs(computed - claimed) <= tolerance + 1e-12 * max(1.0, abs(claimed))
        except EntryError as exc:
            out['discarded'].append({'id': ident, 'field': field, 'reason': str(exc)})
            continue
        record = {'id': ident, 'field': field, 'source': entry['source'], 'claimed': claimed, 'computed': computed}
        if ok:
            out['passed'].append(record)
            continue
        used = {k: state[k] for k in state if re.search(r'(?<![\w$.])' + re.escape(k) + r'(?![\w$])', entry['formula'])}
        record.update(formula=entry['formula'], inputs=used, overrides=overrides)
        out['failed'].append(record)
        where = f'{field}: says "{entry["quote"]}"' if 'quote' in entry and not relative else f'{field}: expects {fmt(claimed)}'
        detail = ', '.join(f'{k}={json.dumps(v)}' for k, v in used.items())
        changed = (' (the reviewer changed ' + ', '.join(overrides) + ' from the page defaults)') if overrides else ''
        out['issues'].append({'origin': 'calculator', 'category': 'math_check',
            'message': f'{where}, but {entry["source"]} gives {fmt(computed)} with {detail or "no inputs"}{changed}.',
            'fix': 'Correct the expected value and compute() together.' if relative else
                   'Correct the stated number, or the preset it describes, so it matches the paper.'})
    return out
