"""One-call review + calculator over a synthetic generator reply, with mocked models."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from agent import Trace
import validator
from validator import validate_reply, generator_feedback, build_review_prompt
from validation_fixtures import CASE, PAPER, CONTENT, reply, review_fixture, content


class ValidatorTests(unittest.TestCase):
    def run_validation(self, text=None, review=None, error=None, runtime_failures=(), calls=1):
        with tempfile.TemporaryDirectory() as tmp:
            trace_path = Path(tmp)/'trace.jsonl'
            client = Mock()
            if error: client.call.side_effect = error
            else: client.call.return_value = json.dumps(review_fixture() if review is None else review)
            report = validate_reply(reply=reply() if text is None else text, paper_md=PAPER, case=CASE,
                                    client=client, trace=Trace(trace_path), runtime_failures=runtime_failures)
            events = [json.loads(line) for line in trace_path.read_text().splitlines()]
        self.assertEqual(client.call.call_count, calls)
        self.assertFalse(report['browser_tested'])
        return report, client, events

    def test_correct_reply_is_approved_with_nothing_for_the_generator(self):
        report, _, events = self.run_validation()
        self.assertTrue(report['approved'], report['result_message'])
        self.assertEqual(report['calculator']['run'], 5)
        self.assertEqual(report['issues'], [])
        self.assertEqual(generator_feedback(report), '')
        self.assertEqual(sum(e['action']=='calculator' and e['result']=='pass' for e in events), 5)

    def test_prompt_carries_paper_education_reply_and_calculator_contract(self):
        _, client, _ = self.run_validation()
        stage, prompt, cap = client.call.call_args.args
        self.assertEqual((stage, cap), ('review', validator.REVIEW_TOKEN_LIMIT))
        self.assertEqual(client.call.call_args.kwargs['system'], validator.SYSTEM)
        for needle in ('Definition 1', 'Straightforward language and audience fit', '<content>', '"calculations"', 'softmaxRows'):
            self.assertIn(needle, prompt)

    def test_only_failed_math_checks_reach_the_generator(self):
        bad = content(); bad['explorations'][0]['observe'] = 'With {x} = 3 the output becomes {y} = 13.'
        review = review_fixture(); review['calculations'][0].update(quote='{y} = 13', value=13)
        report, _, _ = self.run_validation(text=reply(bad), review=review)
        self.assertFalse(report['approved'])
        self.assertEqual([i['origin'] for i in report['issues']], ['calculator'])
        feedback = generator_feedback(report)
        self.assertIn('explorations[0].observe', feedback)
        self.assertIn('gives 12', feedback)
        for passing in ('tests[0].expect.y', 'scenes[0].caption', 'explorations[1].observe'):
            self.assertNotIn(passing, feedback)

    def test_unusable_reviewer_entries_are_logged_not_sent(self):
        review = review_fixture()
        review['calculations'].append({'id':'misquote','field':'explorations[0].observe','quote':'not there','value':1,
                                       'source':'Definition 1','formula':'a * x'})
        report, _, _ = self.run_validation(review=review)
        self.assertTrue(report['approved'])
        self.assertEqual(report['calculator']['discarded'][0]['id'], 'misquote')
        self.assertEqual(report['issues'], [])

    def test_education_failure_or_uncertainty_blocks_approval(self):
        for status in ('fail', 'uncertain'):
            with self.subTest(status=status):
                review = review_fixture()
                review['education'][1].update(status=status, evidence='why uses unexplained jargon.')
                report, _, _ = self.run_validation(review=review)
                self.assertFalse(report['approved'])
                self.assertIn('unexplained jargon', generator_feedback(report))

    def test_reviewer_issue_reaches_generator_with_its_fix(self):
        review = review_fixture()
        review['issues'] = [{'category':'education_requirements','message':'why disagrees with scenes.','fix':'List all steps in why.'}]
        report, _, _ = self.run_validation(review=review)
        self.assertFalse(report['approved'])
        self.assertIn('List all steps in why.', generator_feedback(report))

    def test_reviewer_failures_never_blame_the_generator(self):
        missing = review_fixture(); missing['education'].pop()
        hidden = review_fixture(); hidden['hidden_reasoning'] = 'DO_NOT_LOG_ME'
        no_calcs = review_fixture(); no_calcs.pop('calculations')
        for name, review in (('missing heading', missing), ('extra field', hidden), ('no calculations', no_calcs)):
            with self.subTest(name=name):
                report, _, events = self.run_validation(review=review)
                self.assertFalse(report['approved'])
                self.assertEqual(report['issues'], [])
                self.assertEqual(len(report['validator_errors']), 1)
                self.assertNotIn('DO_NOT_LOG_ME', json.dumps(events))

    def test_model_failure_no_retry_local_checks_still_run(self):
        report, _, _ = self.run_validation(text=reply(content(explorations=CONTENT['explorations'][:1])), error=RuntimeError('unavailable'))
        self.assertFalse(report['approved'])
        self.assertIn('unavailable', report['validator_errors'][0])
        self.assertEqual([i['category'] for i in report['issues']], ['content_structure'])

    def test_unreviewable_reply_spends_no_request(self):
        report, _, _ = self.run_validation(text='<controls>[]</controls>', calls=0)
        self.assertFalse(report['approved'])
        self.assertEqual(report['model_call_invocations'], 0)
        self.assertIn('<content>', report['issues'][0]['message'])

    def test_content_reference_errors_override_model_pass(self):
        def edit(kind):
            c = content()
            if kind == 'unknown_focus': c['explorations'][0]['focus'] = 'missing'
            elif kind == 'unknown_control': c['explorations'][0]['preset'] = {'gain': 4}
            elif kind == 'duplicate_scene': c['scenes'].append(dict(c['scenes'][0]))
            elif kind == 'duplicate_symbol': c['symbols'][1]['key'] = 'a'
            else: c['explorations'][0].pop('why')
            return c
        for kind in ('unknown_focus', 'unknown_control', 'duplicate_scene', 'duplicate_symbol', 'missing_why'):
            with self.subTest(kind=kind):
                report, _, _ = self.run_validation(text=reply(edit(kind)))
                self.assertFalse(report['approved'])
                self.assertIn('content_structure', [i['category'] for i in report['issues']])

    def test_runtime_failures_are_merged(self):
        report, _, _ = self.run_validation(runtime_failures=['test 1: expected y = 6, got 7'])
        self.assertFalse(report['approved'])
        self.assertIn('expected y = 6, got 7', generator_feedback(report))

    def test_empty_paper_fails_before_model(self):
        with self.assertRaises(ValueError):
            build_review_prompt(reply(), '  ', CASE)

    def test_missing_education_rubric_fails_before_model(self):
        client = Mock()
        with tempfile.TemporaryDirectory() as tmp, patch.object(validator, 'EDUCATION_REQUIREMENTS_PATH', Path(tmp)/'missing.md'), self.assertRaises(FileNotFoundError):
            validate_reply(reply=reply(), paper_md=PAPER, case=CASE, client=client, trace=Trace(Path(tmp)/'trace.jsonl'))
        client.call.assert_not_called()

    def test_timeout_is_not_swallowed_or_retried(self):
        client = Mock(); client.call.side_effect = TimeoutError('deadline')
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(TimeoutError):
            validate_reply(reply=reply(), paper_md=PAPER, case=CASE, client=client, trace=Trace(Path(tmp)/'trace.jsonl'))
        client.call.assert_called_once()

    def test_real_client_sends_exactly_one_http_request_and_logs_usage(self):
        from agent import Client
        response = {'usage':{'prompt_tokens':123,'completion_tokens':234},
                    'choices':[{'finish_reason':'stop','message':{'content':'```json\n'+json.dumps(review_fixture())+'\n```'}}]}
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'OPENROUTER_API_KEY':'unit-test-secret'}):
            path = Path(tmp)/'trace.jsonl'; trace = Trace(path); client = Client('supplied-model-id', trace)
            with patch('agent.urllib.request.urlopen', return_value=io.BytesIO(json.dumps(response).encode())) as request:
                report = validate_reply(reply=reply(), paper_md=PAPER, case=CASE, client=client, trace=trace)
            self.assertTrue(report['approved'], report['result_message'])
            request.assert_called_once()
            body = json.loads(request.call_args.args[0].data)
            self.assertEqual(body['model'], 'supplied-model-id')
            self.assertIn('scientific validation subagent', body['messages'][0]['content'])
            self.assertEqual((client.calls, client.completion), (1, 234))
            usage = next(e for e in map(json.loads, path.read_text().splitlines()) if e['action']=='request' and e['result']=='completed')
            self.assertEqual((usage['prompt_tokens'], usage['completion_tokens']), (123, 234))
            self.assertNotIn('unit-test-secret', path.read_text())

    def test_process_deadline_survives_http_client(self):
        from agent import Client, ExecutionDeadlineExceeded
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'OPENROUTER_API_KEY':'test-key'}):
            client = Client('test', Trace(Path(tmp)/'trace.jsonl'))
            with patch('agent.urllib.request.urlopen', side_effect=ExecutionDeadlineExceeded('deadline')), self.assertRaises(ExecutionDeadlineExceeded):
                client.call('review', 'test', 100, system='s')
            self.assertEqual(client.calls, 1)


if __name__ == '__main__':
    unittest.main()
