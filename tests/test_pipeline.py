"""Synthetic, non-paper-specific integration fixture; never used in generation."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import agent


def fixture():
    return {
        'title':'Linear calibration','idea':'A synthetic integration test.','why':'Inspect a simple relationship.',
        'equation':'y = a × x','symbols':[{'symbol':'a','meaning':'gain'}],
        'source':{'title':'Synthetic test source','anchor':'Definition 1','supported':'Multiplication','simplification':'Illustrative scalar example'},
        'limitations':['Only a linear model.'],
        'controls':[{'id':k,'label':k,'kind':'number','value':v,'min':0,'max':10,'step':1,'help':'Change '+k} for k,v in [('a',2),('x',3)]],
        'explorations':[{'title':'Zero input','change':'Set x to zero','observe':'Output is zero','why':'a times zero is zero','values':{'x':0}},
                        {'title':'Double gain','change':'Set a to four','observe':'Output doubles','why':'Output is proportional to gain','values':{'a':4}}],
        'compute':"function compute(p){if(p.a<0||p.x<0)throw Error('Negative input');return {metrics:[{label:'Output',value:p.a*p.x,unit:''}],series:[{label:'Output',values:[{label:'y',value:p.a*p.x}]}],matrices:[],note:'Proportional change',checks:{y:p.a*p.x}}}",
        'tests':[{'name':name,'inputs':{'a':a,'x':x},'expected':{'y':y}} for name,a,x,y in [('zero',2,0,0),('unit',1,1,1),('product',2,3,6)]]
    }

class PipelineTests(unittest.TestCase):
    def run_pipeline(self,broken):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);case=root/'case.json';out=root/'out'
            case.write_text(json.dumps({'source_url':'https://example.org/paper','focus':'Linear scaling','audience':'Undergraduate','excerpt':'Synthetic definition: y equals a times x.'}))
            good=fixture();bad=copy.deepcopy(good);bad['tests'][0]['expected']['y']=99
            replies=[{'concept':'linear'},bad if broken else good]
            if broken:replies.append(good)
            replies.append({'approved':True,'issues':[]})
            with patch.object(agent.Client,'call',side_effect=replies),patch.dict('os.environ',{'OPENROUTER_API_KEY':'fixture-key'}),patch.object(sys,'argv',['agent.py','--input',str(case),'--output',str(out),'--model','fixture']):
                self.assertEqual(agent.main(),0)
            html=(out/'index.html').read_text();events=[json.loads(line) for line in (out/'trace.jsonl').read_text().splitlines()]
            self.assertNotIn('__SPEC_JSON__',html)
            self.assertNotIn('fixture-key',html)
            self.assertEqual(events[-1]['result'],'success')
            self.assertEqual(any(e['stage']=='revise' for e in events),broken)
    def test_complete_pipeline_with_mock_model(self):self.run_pipeline(False)
    def test_failed_numeric_check_triggers_repair(self):self.run_pipeline(True)
    def test_trace_contains_actual_expected_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'trace.jsonl';agent.check(fixture(),agent.Trace(path))
            events=[json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(events[-1]['expected'],{'y':6})
            self.assertEqual(events[-1]['actual'],{'y':6})
