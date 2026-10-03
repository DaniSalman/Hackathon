import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import agent

class Tests(unittest.TestCase):
    def test_calculation_executes(self):
        self.assertEqual(agent.calculate('function compute(p){return {x:p.x*p.x}}',{'x':3}),{'x':9})
    def test_nonfinite_rejected(self):
        with self.assertRaises(Exception):agent.calculate('function compute(p){return {x:0/0}}',{})
    def test_infinite_loop_stopped(self):
        with self.assertRaises(Exception):agent.calculate('function compute(p){while(true){}}',{})
    def test_missing_excerpt_fails(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'case.json';p.write_text(json.dumps(dict(source_url='https://example.org',focus='x',audience='y')))
            with self.assertRaisesRegex(ValueError,'Supply excerpt'):agent.load_case(p)
    def test_expected_arrays(self):
        agent.assert_expected([[1,2],[3,4]],[[1,2],[3,4]],'matrix')
        with self.assertRaises(ValueError):agent.assert_expected([1,2],[1,3],'matrix')
    def test_request_budget_blocks_before_network(self):
        with tempfile.TemporaryDirectory() as t,patch.dict('os.environ',{'OPENROUTER_API_KEY':'test-not-a-real-key'}):
            c=agent.Client('test',agent.Trace(Path(t)/'trace.jsonl'));c.calls=agent.MAX_CALLS
            with self.assertRaises(RuntimeError):c.call('test','hello',100)
    def test_token_reservation_blocks(self):
        with tempfile.TemporaryDirectory() as t,patch.dict('os.environ',{'OPENROUTER_API_KEY':'test-not-a-real-key'}):
            c=agent.Client('test',agent.Trace(Path(t)/'trace.jsonl'));c.reserved=agent.MAX_COMPLETION-10
            with self.assertRaises(RuntimeError):c.call('test','hello',100)
    def test_script_payload_escaped(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'index.html';agent.render({'title':'</script><script>alert(1)</script>'},{'source_url':'https://example.org'},p)
            self.assertNotIn('</script><script>alert',p.read_text())

if __name__=='__main__':unittest.main()
