"""Synthetic test data in the generator's tagged reply format; not a built-in answer or assessment output."""
import copy
import json
from validator import REVIEW_CHECKS, education_requirements

CASE = {'source_url':'https://example.org/paper','excerpt':'Synthetic definition: y equals a times x.',
        'focus':'Linear scaling','audience':'Undergraduate'}
PAPER = '# Synthetic paper\n\n## Definition 1\nThe output is y = a x for gain a and input x.\n'

CONTENT = {
    'title':'Linear gain', 'hook':'What happens to the output when the gain doubles?',
    'why':'A gain scales an input into an output.',
    'symbols':[{'key':'a','meaning':'gain','color':'blue'},{'key':'x','meaning':'input','color':'green'},
               {'key':'y','meaning':'output','color':'gold'}],
    'scenes':[{'id':'s1','title':'Multiply','caption':'The output {y} is {a} times {x}. Dividing by 3 instead gives {y} ≈ 0.667 for {a} = 1, {x} = 2.'}],
    'equation':'{y} = {a}{x}', 'equation_words':'Multiply the gain by the input.',
    'explorations':[
        {'title':'Double the gain','focus':'s1','change':'Set {a} to 4.','preset':{'a':4},
         'observe':'With {x} = 3 the output becomes {y} = 12.','why':'The output is proportional to the gain.'},
        {'title':'Zero input','focus':'s1','change':'Set {x} to 0.','preset':{'x':0},
         'observe':'{y} drops to 0 whatever {a} is.','why':'Anything times zero is zero.'}],
    'takeaway':'Output is proportional to both gain and input.',
    'misconception':'A larger gain does not add a constant; it multiplies.',
    'grounding':{'paper':'Synthetic paper','section':'Definition 1','equation':'y = a x',
                 'from_paper':['y = a x'],'simplifications':['Scalars only.']},
}
CONTROLS = [{'id':'a','type':'slider','label':'gain {a}','min':0,'max':5,'step':0.5,'value':2},
            {'id':'x','type':'slider','label':'input {x}','min':0,'max':5,'step':0.5,'value':3}]
TESTS = [{'state':{'a':2,'x':3},'expect':{'y':6}}, {'state':{'a':1.5,'x':2},'expect':{'y':3}}]


def reply(content=None, controls=None, tests=None):
    return ('<content>\n'+json.dumps(CONTENT if content is None else content, ensure_ascii=False)+'\n</content>\n'
            '<controls>\n'+json.dumps(CONTROLS if controls is None else controls)+'\n</controls>\n'
            '<compute>\nfunction compute(s) { return {y: s.a * s.x}; }\n</compute>\n'
            "<render>\nfunction render(s, r, kit) { kit.readout('#s1', {label: 'y', value: r.y}); }\n</render>\n"
            '<tests>\n'+json.dumps(TESTS if tests is None else tests)+'\n</tests>\n')


def calculations():
    return [
        {'id':'double','field':'explorations[0].observe','quote':'{y} = 12','value':12,'source':'Definition 1','formula':'a * x'},
        {'id':'zero','field':'explorations[1].observe','quote':'drops to 0','value':0,'source':'Definition 1','formula':'a * x'},
        {'id':'third','field':'scenes[0].caption','quote':'{y} ≈ 0.667','value':0.667,'source':'Definition 1',
         'formula':'a * x / 3','inputs':{'a':1,'x':2}},
        {'id':'test0','field':'tests[0].expect.y','source':'Definition 1','formula':'a * x'},
        {'id':'test1','field':'tests[1].expect.y','source':'Definition 1','formula':'a * x'},
    ]


def review_fixture():
    return {
        'summary':'Synthetic review fixture passes.',
        'education':[{'heading':h,'status':'pass','evidence':'Synthetic teaching evidence for '+h} for h in education_requirements()[1]],
        'checks':[{'name':name,'status':'pass','evidence':'Synthetic fixture evidence for '+name} for name in REVIEW_CHECKS],
        'issues':[],
        'calculations':calculations(),
    }


def content(**changes):
    result = copy.deepcopy(CONTENT)
    result.update(changes)
    return result
