"""Opt-in real WAS lookup + configured model, plan-only with no dispatch.

Read private JSON configuration from stdin: was, model_url, key, cases (name,
text, expected_evidence_ids). Supply --out outside the repository. Route WAS and
model via loopback SSH forwards on the QA worker; credentials stay in memory.
Only GET inventory/projected messages and the configured model call are allowed.
The report contains private retrieved excerpts; never commit it to GitHub.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from manager import Manager, MODEL, http_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    config = json.load(sys.stdin)
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    os.environ['MANAGER_READY_DB'] = ''
    report = {'model': MODEL, 'mode': 'real read-only WAS and plan-only model; no dispatch',
              'source_hashes': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in (Path(__file__).resolve().parents[1] / 'app').glob('*.py')}, 'cases': []}
    for case in config['cases']:
        calls, prompts, models = [], [], []
        def readonly(url, body=None, headers=None, method=None, timeout=30):
            if url == config['model_url']:
                assert body and body['model'] == MODEL and method is None
                prompts.append(body['messages'])
                out.with_suffix('.context.json').write_text(json.dumps(body, ensure_ascii=False, indent=2))
            else:
                assert url.startswith(config['was'] + '/api/sessions')
                assert body is None and method is None
                path = urlsplit(url).path.removeprefix(urlsplit(config['was']).path)
                assert path == '/api/sessions' or re.fullmatch(r'/api/sessions/[A-Za-z0-9._:-]+(?:/messages)?', path)
                if case.get('simulate_inventory_failure'):
                    calls.append({'kind': 'injected-WAS-failure', 'path': path})
                    raise OSError('Deliberate lookup failure test')
            headers = dict(headers or {})
            host = config.get('model_host' if body else 'was_host')
            if host:
                headers['Host'] = host  # Preserve original Host through loopback SSH forwarding.
            try:
                response = http_json(url, body, headers, method, timeout)
            except Exception as exc:
                if body and hasattr(exc, 'read'):
                    detail = exc.read().decode(errors='replace').replace(config['key'], '[REDACTED]')
                    print('Model error: ' + detail[:1500], flush=True)
                raise
            calls.append({'kind': 'model' if body else 'WAS-read', 'path': urlsplit(url).path})
            if body:
                models.append(response.get('model'))
            return response
        start = time.monotonic()
        with tempfile.TemporaryDirectory(prefix='lookup-plan-', dir=out.parent) as tmp:
            m = Manager(tmp, was=config['was'], model_url=config['model_url'], key=config['key'], request=readonly)
            m.submit({'text': case['text'], 'request_id': 'isolated_lookup_probe'})
            with m.connect() as c:
                job = dict(c.execute('SELECT * FROM jobs').fetchone())
            plan = m.plan(job)
            context = json.loads(prompts[-1][-1]['content'])
            ids = [s['id'] for s in context['work'] if s.get('evidence')]
            passed = (plan['action'] == 'reply' and models == [MODEL]
                      and all(sid in ids for sid in case.get('expected_evidence_ids', [])))
            if case.get('simulate_inventory_failure'):
                passed &= context['lookup']['state'] == 'unavailable'
            if case.get('expect_no_evidence'):
                passed &= not ids and context['lookup']['absence_proven'] is False
            if case.get('expect_no_dispatch', True):
                with m.connect() as c:
                    assert c.execute('SELECT status FROM jobs').fetchone()[0] == 'queued'
                    assert c.execute("SELECT count(*) FROM messages WHERE role='assistant'").fetchone()[0] == 0
            result = {'name': case['name'], 'seconds': round(time.monotonic()-start, 3),
                      'passed': passed, 'plan': plan, 'context': context, 'models': models,
                      'calls': calls, 'expected_evidence_ids': case.get('expected_evidence_ids', [])}
            report['cases'].append(result)
            report['passed'] = sum(c['passed'] for c in report['cases'])
            report['total'] = len(report['cases'])
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
            print(json.dumps({k:v for k,v in result.items() if k not in ('context', 'calls')}, ensure_ascii=False), flush=True)
            print(json.dumps({'lookup': context['lookup'], 'evidence_ids': ids}), flush=True)
    return 0 if report['passed'] == report['total'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
