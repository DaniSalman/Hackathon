"""Every check on a generator reply lives here; the generator only generates.

    v = Validator(case, case_path, client, trace, budget)
    report = v.check(reply_text)   # {'ok', 'complete', 'failures', 'passed', ...}

Stage 1  runtime checks (runtime.py): free, on every reply.
Stage 2  review (review.py): one model call, only once stage 1 passes, at most MAX_REVIEWS per run.
Stage 3  calculator (calculator.py): evaluates the review's entries, free.
Once no review is left (count, tokens or time), the stored entries are rechecked for free and the
earlier review is trusted. report['failures'] holds only what the generator must fix; passing
checks and unusable reviewer entries go to the trace.
"""
from pathlib import Path
from template.assemble import loads_lenient, parse_reply
from . import calculator, review, runtime

MAX_REVIEWS = 2
REVIEW_TOKENS = 5000        # reasoning tokens count inside this cap
REVIEW_REASONING = 'off'   # measured: 'minimal' spent the whole 5,000-token cap reasoning over a full paper
MIN_REVIEW_TOKENS = 3000
MIN_REVIEW_SECONDS = 90


def load_paper(case, case_path):
    """The full paper, converted beforehand, named by case['paper_md'] relative to the case file."""
    ref = case.get('paper_md')
    if not isinstance(ref, str) or not ref.strip():
        return None, 'case.json has no paper_md field'
    path = Path(case_path).resolve().parent / ref
    try:
        text = path.read_text(encoding='utf-8')
    except OSError as exc:
        return None, f'cannot read paper_md {ref}: {exc.strerror or exc}'
    if not text.strip():
        return None, f'paper_md {ref} is empty'
    return text, None


def as_failure(issue):
    return f"[{issue['origin']}/{issue['category']}] {issue['message']} Fix: {issue['fix']}"


def no_limit():
    return {'tokens': 10**9, 'seconds': 10**9, 'calls': 10**9}


class Validator:
    def __init__(self, case, case_path, client, trace, budget=no_limit):
        self.case, self.client, self.trace, self.budget = case, client, trace, budget
        self.paper, self.paper_problem = load_paper(case, case_path)
        self.reviews = 0
        self.entries = None   # calculator entries from the latest successful review
        trace.log('validation', 'load_paper', 'passed' if self.paper else 'skipped',
                  paper_characters=len(self.paper) if self.paper else 0, problem=self.paper_problem)

    def can_review(self):
        left = self.budget()
        return (self.reviews < MAX_REVIEWS and left['calls'] >= 1 and left['tokens'] >= MIN_REVIEW_TOKENS
                and left['seconds'] >= MIN_REVIEW_SECONDS)

    def check(self, reply):
        rt = runtime.validate(reply)
        minor = list(rt.get('minor', []))   # runtime failures logged as warnings, never repaired on their own
        report = {'ok': rt['ok'], 'complete': False, 'stage': 'runtime', 'failures': list(rt['failures']), 'minor': minor,
                  'passed': list(rt['passed']), 'review': None, 'calculator': None, 'validator_errors': []}
        if any(f not in minor for f in rt['failures']):
            return report   # no request spent reviewing a reply that does not run
        if runtime.js_engine() is None:
            # Nothing executed the generated code and nothing can run calculator formulas: never report success.
            report['validator_errors'].append('no JavaScript engine: runtime and calculator checks were skipped')
            self.trace.log('validation', 'engine', 'missing', note='install the pinned quickjs package')
            return report
        parts = parse_reply(reply)
        content, controls, tests = (loads_lenient(parts['content'], {}), loads_lenient(parts['controls'], []),
                                    loads_lenient(parts.get('tests'), []))
        if self.paper is None:
            report['validator_errors'].append('review skipped: ' + self.paper_problem)
            self.trace.log('validation', 'review', 'skipped', reason=self.paper_problem)
            return report
        issues = []
        while self.can_review():
            self.reviews += 1
            try:
                messages, headings = review.build_messages(reply, self.paper, self.case)
                text, finish = self.client.chat('review', messages, min(REVIEW_TOKENS, self.budget()['tokens']),
                                              reasoning=REVIEW_REASONING, json_mode=True)
                if finish == 'length':
                    raise ValueError('review reply was cut off at the token cap')
                parsed = review.parse_review(text, headings)
            except TimeoutError:
                raise   # the process deadline
            except Exception as exc:   # never the generator's fault: no failure for it, maybe another review
                message = str(exc) or type(exc).__name__
                report['validator_errors'].append(f'review {self.reviews} failed: {message}')
                self.trace.log('validation', 'review', 'failed', review=self.reviews, error=message[:300])
                continue
            self.entries = parsed['calculations']
            self.trace.log('validation', 'review', 'completed', review=self.reviews, summary=parsed['summary'],
                           education=parsed['education'], checks=parsed['checks'], issues=parsed['issues'],
                           calculation_entries=len(self.entries))
            report.update(stage='review', review={k: v for k, v in parsed.items() if k != 'calculations'})
            calc_issues = self._calculate(report, content, controls, tests, recheck=False)
            review_issues, withheld = review.findings(parsed, reply + '\n' + self.paper, report['calculator']['passed'])
            for item in withheld:   # the calculator is the only judge of numbers
                self.trace.log('validation', 'review_finding', 'withheld', category=item['category'],
                               reason=item['withheld'], message=item['message'][:300])
            report['review']['withheld'] = withheld
            issues += review_issues + calc_issues
            report['complete'] = True
            break
        else:
            if self.entries is not None:
                issues += self._calculate(report, content, controls, tests, recheck=True)
                report.update(stage='recheck', complete=True)   # the earlier review is trusted
            else:
                self.trace.log('validation', 'review', 'skipped', reason='no review budget left', reviews=self.reviews)
        if not issues and report['complete']:
            report['passed'].append(report['stage'])
        report['failures'] += [as_failure(issue) for issue in issues]
        report['ok'] = not report['failures']
        return report

    def _calculate(self, report, content, controls, tests, recheck):
        calc = calculator.run(self.entries, content, controls, tests, recheck=recheck)
        mode = 'recheck' if recheck else 'check'
        for result, records in (('pass', calc['passed']), ('fail', calc['failed'])):
            for record in records:
                self.trace.log('validation', 'calculator', result, mode=mode, check=record['id'], field=record['field'],
                               claimed=record['claimed'], computed=record['computed'])
        for record in calc['discarded']:
            self.trace.log('validation', 'calculator', 'discarded', mode=mode, check=record['id'], field=record['field'],
                           quote=record.get('quote'), formula=record.get('formula'), reason=record['reason'])
        report['passed'] += [f"calculator: {record['field']}" for record in calc['passed']]
        report['calculator'] = {'mode': mode, 'passed': calc['passed'], 'failed': calc['failed'], 'discarded': calc['discarded']}
        return calc['issues']
