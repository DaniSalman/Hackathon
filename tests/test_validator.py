"""Validator: runtime checks, then one review + calculator, with a mocked model client."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import agent
from validator import Validator, MAX_REVIEWS, review as review_module
from validation_fixtures import CASE, PAPER, TESTS, reply, review_fixture, content


def chat_returning(*reviews, finish='stop'):
    client = Mock()
    client.chat.side_effect = [(r if isinstance(r, str) else json.dumps(r), finish) for r in reviews]
    return client


def wrong_number_reply():
    bad = content(); bad['explorations'][0]['observe'] = 'With {x} = 3 the output becomes {y} = 13.'
    return reply(bad)


def review_of_wrong_number():
    r = review_fixture(); r['calculations'][0].update(quote='{y} = 13', value=13)
    return r


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root/'paper.md').write_text(PAPER)
        self.trace_path = self.root/'trace.jsonl'

    def make(self, client, case=CASE, budget=None):
        trace = agent.Trace(self.trace_path)
        kwargs = {} if budget is None else {'budget': budget}
        return Validator(case, self.root/'case.json', client, trace, **kwargs)

    def events(self):
        return [json.loads(line) for line in self.trace_path.read_text().splitlines()]

    def test_correct_reply_passes_after_one_review(self):
        client = chat_returning(review_fixture())
        report = self.make(client).check(reply())
        self.assertEqual(client.chat.call_count, 1)
        self.assertEqual((report['ok'], report['complete'], report['stage'], report['failures']), (True, True, 'review', []))
        self.assertEqual(len(report['calculator']['passed']), 5)
        self.assertEqual(sum(e['action'] == 'calculator' and e['result'] == 'pass' for e in self.events()), 5)

    def test_review_request_carries_paper_rubric_reply_and_contract(self):
        client = chat_returning(review_fixture())
        self.make(client).check(reply())
        stage, messages, cap = client.chat.call_args.args
        self.assertEqual(stage, 'review')
        self.assertLessEqual(cap, 5000)
        self.assertEqual(messages[0]['content'], review_module.SYSTEM)
        for needle in ('Definition 1', 'Straightforward language and audience fit', '<content>', '"calculations"', 'softmaxRows'):
            self.assertIn(needle, messages[1]['content'])

    def test_runtime_failure_spends_no_review(self):
        tests = copy.deepcopy(TESTS); tests[0]['expect']['y'] = 7
        client = chat_returning()
        report = self.make(client).check(reply(tests=tests))
        client.chat.assert_not_called()
        self.assertEqual(report['stage'], 'runtime')
        self.assertTrue(any('expected y = 7' in f for f in report['failures']))

    def test_only_failed_math_checks_reach_the_generator(self):
        report = self.make(chat_returning(review_of_wrong_number())).check(wrong_number_reply())
        self.assertFalse(report['ok'])
        self.assertEqual(len(report['failures']), 1)
        self.assertIn('[calculator/math_check] explorations[0].observe', report['failures'][0])
        self.assertIn('gives 12', report['failures'][0])

    def test_unusable_reviewer_entries_are_logged_not_sent(self):
        r = review_fixture()
        r['calculations'].append({'id':'misquote','field':'explorations[0].observe','quote':'not there','value':1,
                                  'source':'Definition 1','formula':'a * x'})
        report = self.make(chat_returning(r)).check(reply())
        self.assertTrue(report['ok'])
        self.assertEqual(report['calculator']['discarded'][0]['id'], 'misquote')

    def test_education_failure_or_uncertainty_reaches_generator(self):
        for status in ('fail', 'uncertain'):
            with self.subTest(status=status):
                r = review_fixture(); r['education'][1].update(status=status, evidence='why uses unexplained jargon.')
                r['issues'] = [{'category':'education_requirements','message':'why is vague.','fix':'Define gain first.'}]
                report = self.make(chat_returning(r)).check(reply())
                self.assertFalse(report['ok'])
                self.assertTrue(any('unexplained jargon' in f for f in report['failures']))
                self.assertTrue(any('Define gain first.' in f for f in report['failures']))

    def test_bad_review_is_retried_once_and_never_blames_the_generator(self):
        missing = review_fixture(); missing['education'].pop()
        bad_status = review_fixture(); bad_status['checks'][0]['status'] = 'probably fine'
        client = chat_returning(missing, bad_status)
        report = self.make(client).check(reply())
        self.assertEqual(client.chat.call_count, MAX_REVIEWS)
        self.assertEqual((report['ok'], report['complete'], report['failures']), (True, False, []))
        self.assertEqual(len(report['validator_errors']), 2)

    def test_formatting_slips_are_tolerated_and_extras_never_logged(self):
        r = review_fixture(); r['hidden_reasoning'] = 'DO_NOT_LOG_ME'; r['education'][0]['note'] = 'DO_NOT_LOG_ME'
        r['issues'] = [{'category':'visual_and_interaction_alignment','message':'Caption s1 never says what y means.',
                        'fix':'Define y in the caption.','severity':'DO_NOT_LOG_ME'}]
        client = chat_returning(json.dumps(r) + '"}')     # stray characters after the object, seen live
        report = self.make(client).check(reply())
        self.assertTrue(report['complete'])
        self.assertEqual(report['failures'], ['[review/education_requirements] Caption s1 never says what y means. Fix: Define y in the caption.'])
        self.assertNotIn('DO_NOT_LOG_ME', self.trace_path.read_text())

    def test_reviewer_arithmetic_is_withheld_from_the_generator(self):
        r = review_fixture()
        r['issues'] = [{'category':'scientific_accuracy','message':'explorations[0] says y = 12 but the preset gives 11.25.',
                        'fix':'Use 11.25.'}]
        report = self.make(chat_returning(r)).check(reply())
        self.assertEqual((report['ok'], report['failures']), (True, []))
        self.assertIn('reviewer arithmetic: 11.25', report['review']['withheld'][0]['withheld'])

    def test_finding_that_disputes_a_verified_number_is_overruled(self):
        r = review_fixture()
        r['education'][5].update(status='fail', evidence='scenes[0].caption: {y} ≈ 0.667 is wrong for these inputs.')
        report = self.make(chat_returning(r)).check(reply())
        self.assertEqual((report['ok'], report['failures']), (True, []))
        self.assertIn('overruled by calculator: 0.667', report['review']['withheld'][0]['withheld'])

    def test_bad_review_then_good_review_completes(self):
        client = chat_returning('not json', review_fixture())
        report = self.make(client).check(reply())
        self.assertEqual((client.chat.call_count, report['complete'], report['ok']), (2, True, True))

    def test_truncated_review_is_a_validator_error(self):
        client = chat_returning(review_fixture(), review_fixture(), finish='length')
        report = self.make(client).check(reply())
        self.assertFalse(report['complete'])
        self.assertIn('cut off', report['validator_errors'][0])

    def test_after_a_repair_second_review_then_free_recheck(self):
        client = chat_returning(review_of_wrong_number(), review_fixture())
        v = self.make(client)
        first = v.check(wrong_number_reply())
        self.assertFalse(first['ok'])
        second = v.check(reply())                     # repaired: second review
        self.assertEqual((client.chat.call_count, second['stage'], second['ok']), (2, 'review', True))
        third = v.check(wrong_number_reply())         # no reviews left: stored entries, no call
        self.assertEqual((client.chat.call_count, third['stage'], third['complete']), (2, 'recheck', True))
        self.assertTrue(any('closest number is 13' in f for f in third['failures']))

    def test_no_budget_left_means_no_review(self):
        client = chat_returning(review_fixture())
        report = self.make(client, budget=lambda: {'tokens': 1000, 'seconds': 300, 'calls': 3}).check(reply())
        client.chat.assert_not_called()
        self.assertEqual((report['ok'], report['complete']), (True, False))

    def test_missing_paper_skips_review(self):
        for case in ({k: v for k, v in CASE.items() if k != 'paper_md'}, {**CASE, 'paper_md': 'nope.md'}):
            with self.subTest(paper_md=case.get('paper_md')):
                client = chat_returning(review_fixture())
                report = self.make(client, case=case).check(reply())
                client.chat.assert_not_called()
                self.assertEqual((report['ok'], report['complete']), (True, False))
                self.assertIn('review skipped', report['validator_errors'][0])

    def test_missing_engine_is_never_reported_as_success(self):
        client = chat_returning(review_fixture())
        v = self.make(client)
        with patch('validator.runtime.js_engine', return_value=None):
            report = v.check(reply())
        client.chat.assert_not_called()
        self.assertEqual((report['complete'], report['validator_errors']),
                         (False, ['no JavaScript engine: runtime and calculator checks were skipped']))

    def test_timeout_is_not_swallowed(self):
        client = Mock(); client.chat.side_effect = TimeoutError('deadline')
        with self.assertRaises(TimeoutError):
            self.make(client).check(reply())
        client.chat.assert_called_once()

    def test_budget_exhaustion_inside_the_client_is_a_validator_error(self):
        client = Mock(); client.chat.side_effect = RuntimeError('request, time or completion-token budget exhausted')
        report = self.make(client).check(reply())
        self.assertEqual((report['ok'], report['complete'], report['failures']), (True, False, []))


if __name__ == '__main__':
    unittest.main()
