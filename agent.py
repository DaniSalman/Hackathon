#!/usr/bin/env python3
"""Paper to Playground: bounded plan → build → execute checks → review → repair."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import signal
import sys
import time
import urllib.request
import urllib.error
from urllib.parse import urlparse
import quickjs
from prompts import SYSTEM, PLAN, GENERATE, REVIEW

ENDPOINT = 'https://openrouter.ai/api/v1/chat/completions'
START = time.monotonic()
MAX_SECONDS = 570
MAX_CALLS = 8
MAX_COMPLETION = 29000

class Trace:
    def __init__(self, path):
        self.path = path
        path.write_text('', encoding='utf-8')
    def log(self, stage, action, result, **extra):
        event = dict(stage=stage, action=action, result=result,
                     elapsed_seconds=round(time.monotonic()-START, 3), **extra)
        with self.path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(event, ensure_ascii=False, allow_nan=False)+'\n')

class Client:
    def __init__(self, model, trace):
        self.model, self.trace = model, trace
        self.calls = self.completion = self.reserved = 0
        self.key = os.environ.get('OPENROUTER_API_KEY')
        if not self.key:
            raise ValueError('Set OPENROUTER_API_KEY in the environment; no credential is embedded or logged.')
    def call(self, stage, prompt, cap):
        remaining = MAX_SECONDS - (time.monotonic()-START)
        if self.calls >= MAX_CALLS or remaining < 15 or self.reserved + cap > MAX_COMPLETION:
            raise RuntimeError('Request, time, or completion-token budget exhausted')
        self.calls += 1
        self.reserved += cap  # Reserve even failed requests: never gamble on unreported usage.
        body = json.dumps(dict(model=self.model, max_tokens=cap,
            messages=[dict(role='system',content=SYSTEM),dict(role='user',content=prompt)])).encode()
        self.trace.log(stage, 'request', 'started', call=self.calls, max_tokens=cap, model=self.model)
        req = urllib.request.Request(ENDPOINT, data=body, method='POST', headers={
            'Content-Type':'application/json', 'Authorization':'Bearer '+self.key})
        try:
            with urllib.request.urlopen(req, timeout=min(120, remaining-5)) as response:
                data = json.load(response)
        except (urllib.error.URLError, TimeoutError) as exc:
            self.trace.log(stage, 'request', 'failed', call=self.calls, error_type=type(exc).__name__,
                           prompt_tokens=None, completion_tokens=None, usage_verifiable=False)
            raise RuntimeError('OpenRouter request failed; see trace (credentials omitted)') from None
        usage = data.get('usage', {})
        pt, ct = usage.get('prompt_tokens'), usage.get('completion_tokens')
        if type(pt) is not int or type(ct) is not int or pt < 0 or ct < 0:
            raise ValueError('OpenRouter response lacks verifiable token usage')
        self.reserved += ct-cap
        self.completion += ct
        self.trace.log(stage, 'request', 'completed', call=self.calls, prompt_tokens=pt,
                       completion_tokens=ct, total_tokens=pt+ct, usage_verifiable=True)
        choice = data['choices'][0]
        if choice.get('finish_reason') == 'length':
            raise ValueError('Model output truncated; reduce the specification size')
        content = choice['message']['content'].strip()
        if content.startswith('```'):
            content = re.sub(r'^```(?:json)?\s*|\s*```$', '', content)
        return json.loads(content)

def load_case(path):
    case = json.loads(path.read_text(encoding='utf-8'))
    for key in ('source_url','focus','audience'):
        if not isinstance(case.get(key), str) or not case[key].strip():
            raise ValueError(f'Missing nonempty string field: {key}')
    url = urlparse(case['source_url'])
    if url.scheme not in ('http','https') or not url.netloc:
        raise ValueError('source_url must be an HTTP(S) paper URL')
    excerpts = [case[k] for k in ('excerpt','source_excerpt','paper_excerpt','source_text') if k in case]
    if not excerpts or not isinstance(excerpts[0],str) or not excerpts[0].strip():
        raise ValueError('Supply excerpt (or source_excerpt/paper_excerpt/source_text). Assessment permits only OpenRouter network access; source URLs cannot be fetched.')
    if len(set(excerpts)) != 1:
        raise ValueError('Conflicting excerpt fields; provide one authoritative excerpt')
    if len(excerpts[0]) > 65000:
        raise ValueError('Excerpt exceeds 65,000 characters; supply only the focused section')
    return {**case,'excerpt':excerpts[0]}

def finite(value):
    if isinstance(value, (int,float)) and not isinstance(value,bool):
        return math.isfinite(value)
    if isinstance(value,list):
        return all(finite(v) for v in value)
    return False

def validate(spec):
    for key in ('title','idea','why','equation','compute'):
        if not isinstance(spec.get(key),str) or not spec[key].strip():
            raise ValueError('Missing specification text: '+key)
    for key in ('symbols','limitations','controls','explorations','tests'):
        if not isinstance(spec.get(key),list) or not spec[key]:
            raise ValueError('Missing specification list: '+key)
    for key in ('title','anchor','supported','simplification'):
        if not isinstance(spec.get('source',{}).get(key),str) or not spec['source'][key].strip():
            raise ValueError('Missing source grounding: '+key)
    if len(spec['controls']) < 2 or len(spec['explorations']) < 2 or len(spec['tests']) < 3:
        raise ValueError('Need two controls, two explorations and three numeric tests')
    ids = set()
    for c in spec['controls']:
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',c['id']) or c['id'] in ids:
            raise ValueError('Invalid or duplicate control id')
        ids.add(c['id'])
        for k in ('label','help'):
            if not isinstance(c.get(k),str): raise ValueError('Control missing '+k)
        kind, v = c['kind'], c['value']
        if kind == 'number':
            if not all(finite(c[k]) for k in ('value','min','max','step')) or not c['min']<=v<=c['max'] or c['step']<=0:
                raise ValueError('Invalid numeric control bounds')
        elif kind == 'boolean':
            if type(v) is not bool: raise ValueError('Boolean control requires boolean')
        elif kind == 'vector':
            if not isinstance(v,list) or not v or not all(finite(x) and not isinstance(x,list) for x in v): raise ValueError('Invalid vector')
        elif kind == 'matrix':
            if not isinstance(v,list) or not v or not all(isinstance(row,list) and row and len(row)==len(v[0]) and all(finite(x) and not isinstance(x,list) for x in row) for row in v): raise ValueError('Invalid rectangular matrix')
        else: raise ValueError('Unknown control kind: '+kind)
    for e in spec['explorations']:
        for k in ('title','change','observe','why'):
            if not isinstance(e.get(k),str) or not e[k]: raise ValueError('Incomplete exploration: '+k)
        if not isinstance(e.get('values'),dict) or not set(e['values'])<=ids: raise ValueError('Unknown exploration control')
    if re.search(r'\b(?:fetch|XMLHttpRequest|WebSocket|import|require|eval|Function|document|window|globalThis)\b|</script',spec['compute']):
        raise ValueError('Computation must be pure JavaScript without external capabilities')

def calculate(code, inputs):
    context = quickjs.Context()
    context.set_memory_limit(16*1024*1024)
    context.set_time_limit(0.3)
    context.eval(code)
    raw = context.eval('JSON.stringify(compute('+json.dumps(inputs,allow_nan=False)+'), (k,v)=>{if(typeof v==="number"&&!Number.isFinite(v))throw Error("Non-finite calculation");return v;})')
    return json.loads(raw)

def assert_expected(actual, expected, label):
    if isinstance(expected,list):
        if not isinstance(actual,list) or len(actual)!=len(expected): raise ValueError(label+': array shape mismatch')
        for i,(a,e) in enumerate(zip(actual,expected)): assert_expected(a,e,f'{label}[{i}]')
    elif not finite(expected) or isinstance(actual,bool) or not isinstance(actual,(int,float)) or not math.isclose(actual,expected,rel_tol=1e-9,abs_tol=1e-10):
        raise ValueError(f'{label}: expected {expected}, got {actual}')

def check_result(result):
    for key in ('metrics','series','matrices'):
        if not isinstance(result.get(key),list): raise ValueError('Calculation missing '+key)
    if not result['metrics'] or not (result['series'] or result['matrices']): raise ValueError('Calculation needs metrics and a visual')
    for m in result['metrics']:
        if not isinstance(m.get('label'),str) or not finite(m.get('value')) or isinstance(m['value'],list): raise ValueError('Invalid metric')
    for s in result['series']:
        if not isinstance(s.get('label'),str) or not s.get('values'): raise ValueError('Invalid chart series')
        for v in s['values']:
            if not isinstance(v.get('label'),str) or not finite(v.get('value')) or isinstance(v['value'],list): raise ValueError('Invalid chart value')
    for m in result['matrices']:
        rows=m['values']
        if not rows or not all(isinstance(row,list) and row and len(row)==len(rows[0]) and all(finite(v) and not isinstance(v,list) for v in row) for row in rows): raise ValueError('Invalid output matrix')
    if not isinstance(result.get('note'),str) or not isinstance(result.get('checks'),dict): raise ValueError('Missing interpretation or numeric checks')

def check(spec, trace):
    validate(spec)
    defaults = {c['id']:c['value'] for c in spec['controls']}
    cases = [('default',defaults)] + [(e['title'],{**defaults,**e['values']}) for e in spec['explorations']]
    for name,inputs in cases:
        check_result(calculate(spec['compute'],inputs))
        trace.log('check','execute', 'passed', check=name)
    for test in spec['tests']:
        if set(test['inputs']) != set(defaults) or not test.get('expected'): raise ValueError('Test must supply all inputs and expected numeric values')
        r = calculate(spec['compute'], test['inputs'])
        check_result(r)
        for key,expected in test['expected'].items(): assert_expected(r['checks'][key],expected,test['name']+'.'+key)
        trace.log('check','numerical', 'passed', check=test['name'], expected=test['expected'], actual={k:r['checks'][k] for k in test['expected']})

def render(spec, case, target):
    data = json.dumps({**spec,'source_url':case['source_url']},ensure_ascii=False).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    template = Path(__file__).with_name('template.html').read_text(encoding='utf-8')
    target.write_text(template.replace('__SPEC_JSON__',data),encoding='utf-8')

def timeout_handler(*_):
    raise TimeoutError('Hard execution deadline reached')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--model',required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    trace=Trace(args.output/'trace.jsonl')
    if hasattr(signal,'SIGALRM'):
        signal.signal(signal.SIGALRM,timeout_handler)
        signal.alarm(max(1,int(MAX_SECONDS-(time.monotonic()-START))))
    try:
        if (args.output/'index.html').exists(): raise ValueError('Use a fresh output directory; index.html already exists')
        case=load_case(args.input)
        trace.log('input','validate','passed',source_url=case['source_url'],excerpt_characters=len(case['excerpt']))
        client=Client(args.model,trace)
        source=json.dumps(case,ensure_ascii=False)
        plan=client.call('plan',PLAN+'\nINPUT DATA:\n'+source,1800)
        (args.output/'plan.json').write_text(json.dumps(plan,indent=2,ensure_ascii=False),encoding='utf-8')
        spec=client.call('generate',GENERATE+'\nINPUT DATA:\n'+source+'\nPLAN:\n'+json.dumps(plan),6500)
        for attempt in range(3):
            issues=[]
            try:
                check(spec,trace)
            except Exception as exc:
                issues=[str(exc)]
                trace.log('check','validate','failed',error=str(exc),revision=attempt)
            if not issues:
                review=client.call('review',REVIEW+'\nINPUT DATA:\n'+source+'\nSPEC:\n'+json.dumps(spec),1200)
                trace.log('review','audit',review)
                if review.get('approved') is True and review.get('issues') == []:
                    render(spec,case,args.output/'index.html')
                    (args.output/'spec.json').write_text(json.dumps(spec,indent=2,ensure_ascii=False),encoding='utf-8')
                    trace.log('finish','write','success',file='index.html',calls=client.calls,completion_tokens=client.completion,
                              browser_tested=False,checks='QuickJS computation + schema + model source review')
                    print(str((args.output/'index.html').resolve()))
                    return 0
                issues=review.get('issues') or ['Reviewer did not approve']
            if attempt == 2: raise ValueError('Unresolved after two revisions: '+json.dumps(issues))
            trace.log('revise','repair','started',revision=attempt+1,issues=issues)
            spec=client.call('repair',GENERATE+'\nRepair these issues: '+json.dumps(issues)+'\nINPUT DATA:\n'+source+'\nCURRENT SPEC:\n'+json.dumps(spec),6500)
        raise RuntimeError('No successful artifact')
    except Exception as exc:
        trace.log('finish','abort','failed',error=str(exc))
        print('Generation failed: '+str(exc),file=sys.stderr)
        return 1
    finally:
        if hasattr(signal,'SIGALRM'): signal.alarm(0)

if __name__=='__main__': sys.exit(main())
