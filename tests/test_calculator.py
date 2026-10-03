"""Calculator entries against a synthetic reply; no model involved."""
import copy
import unittest
import calculator
from validation_fixtures import CONTENT, CONTROLS, TESTS, calculations


def run(entries, content=None, tests=None):
    return calculator.run(entries, copy.deepcopy(CONTENT) if content is None else content, CONTROLS,
                          copy.deepcopy(TESTS) if tests is None else tests)


def entry(**changes):
    base = {'id':'e','field':'explorations[0].observe','quote':'{y} = 12','value':12,'source':'Definition 1','formula':'a * x'}
    base.update(changes)
    return base


class CalculatorTests(unittest.TestCase):
    def test_correct_claims_pass_and_produce_no_issues(self):
        out = run(calculations())
        self.assertEqual([r['id'] for r in out['passed']], ['double','zero','third','test0','test1'])
        self.assertEqual((out['failed'], out['discarded'], out['issues']), ([], [], []))

    def test_wrong_text_number_becomes_generator_issue(self):
        content = copy.deepcopy(CONTENT)
        content['explorations'][0]['observe'] = 'With {x} = 3 the output becomes {y} = 13.'
        out = run([entry(quote='{y} = 13', value=13)], content=content)
        self.assertEqual(len(out['issues']), 1)
        message = out['issues'][0]['message']
        self.assertIn('explorations[0].observe', message)
        self.assertIn('gives 12', message)
        self.assertIn('a=4', message)  # the preset value, not the default

    def test_preset_is_injected_from_the_reply(self):
        out = run([entry()])
        self.assertEqual(out['passed'][0]['computed'], 12)

    def test_rounding_follows_written_precision(self):
        content = copy.deepcopy(CONTENT)
        for written, ok in (('0.667', True), ('0.67', True), ('0.7', True), ('0.66', False)):
            with self.subTest(written=written):
                content['scenes'][0]['caption'] = f'Dividing by 3 gives {{y}} ≈ {written} for {{a}} = 1.'
                out = run([entry(field='scenes[0].caption', quote=f'{{y}} ≈ {written}', value=float(written),
                                 formula='a * x / 3', inputs={'a':1,'x':2})], content=content)
                self.assertEqual(bool(out['passed']), ok)

    def test_written_tolerance(self):
        self.assertEqual(calculator.written_tolerance('0.998'), 0.0005)
        self.assertEqual(calculator.written_tolerance('580'), 5)
        self.assertEqual(calculator.written_tolerance('9'), 0.5)
        self.assertEqual(calculator.written_tolerance('−3.5'), 0.05)

    def test_number_at_sentence_end_is_found(self):
        content = copy.deepcopy(CONTENT)
        content['explorations'][0]['observe'] = 'The output is 12.'
        self.assertTrue(run([entry(quote='output is 12.', value=12)], content=content)['passed'])

    def test_wrong_test_expectation_becomes_generator_issue(self):
        tests = copy.deepcopy(TESTS); tests[1]['expect']['y'] = 4
        out = run([entry(field='tests[1].expect.y', quote=None, value=None)], tests=tests)
        self.assertEqual(len(out['issues']), 1)
        self.assertIn('expects 4', out['issues'][0]['message'])
        self.assertIn('compute()', out['issues'][0]['fix'])

    def test_array_expectations_compare_elementwise(self):
        tests = [{'state':{'a':2,'x':3},'expect':{'v':[6, 12]}}]
        ok = run([entry(field='tests[0].expect.v', formula='[a * x, 2 * a * x]')], tests=tests)
        self.assertEqual(len(ok['passed']), 1)
        shape = run([entry(field='tests[0].expect.v', formula='a * x')], tests=tests)
        self.assertEqual(shape['issues'], [])
        self.assertIn('shapes', shape['discarded'][0]['reason'])

    def test_reviewer_errors_are_discarded_not_blamed(self):
        cases = {
            'quote does not appear': entry(quote='{y} = 99'),
            'not written in the quote': entry(value=11),
            'does not exist': entry(field='explorations[5].observe'),
            'unreadable field path': entry(field='explorations..observe'),
            'formula failed': entry(formula='a *'),
            'finite': entry(formula='a / 0'),
            'contradict the preset': entry(inputs={'a':2}),
            'needs id, field, source and formula': entry(source=''),
        }
        for reason, bad in cases.items():
            with self.subTest(reason=reason):
                out = run([bad])
                self.assertEqual(out['issues'], [])
                self.assertIn(reason, out['discarded'][0]['reason'])

    def test_runaway_formula_is_stopped(self):
        out = run([entry(formula='(() => { while (true) {} })()')])
        self.assertEqual(out['issues'], [])
        self.assertEqual(len(out['discarded']), 1)

    def test_entry_limit(self):
        out = run([entry()] * (calculator.MAX_ENTRIES + 2))
        self.assertEqual(len(out['passed']), calculator.MAX_ENTRIES)
        self.assertEqual(len(out['discarded']), 2)

    def test_non_list_is_discarded(self):
        out = calculator.run({'not':'a list'}, CONTENT, CONTROLS, TESTS)
        self.assertEqual((out['issues'], len(out['discarded'])), ([], 1))


if __name__ == '__main__':
    unittest.main()
