"""Validate one saved generator reply: runtime checks, then (if they pass) one review + calculator.

    python -m validator --input examples/attention.json --reply out/reply.txt --output check-out --model MODEL_ID

The case's paper_md field names the converted paper. Writes check-out/validation.json and trace.jsonl.
Exit 0 = no failures and the review ran; 2 = no failures but the review could not run; 1 = failures.
"""
import argparse
import json
from pathlib import Path
import sys
from . import Validator


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--reply', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model', required=True)
    args = parser.parse_args()
    import agent
    args.output.mkdir(parents=True, exist_ok=True)
    trace = agent.Trace(args.output / 'trace.jsonl')
    try:
        case = agent.load_case(args.input, trace)
        report = Validator(case, args.input, agent.Client(args.model, trace), trace).check(args.reply.read_text(encoding='utf-8'))
    except Exception as exc:
        trace.log('validation', 'abort', 'failed', error=str(exc)[:300])
        print('Validation failed: ' + str(exc), file=sys.stderr)
        return 1
    (args.output / 'validation.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    for line in report['failures'] + report['validator_errors']:
        print('- ' + line)
    return 1 if report['failures'] else 0 if report['complete'] else 2


if __name__ == '__main__':
    sys.exit(main())
