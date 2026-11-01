"""Opt-in real Sonnet/worker acceptance in an isolated app/project.

Uses real WAS only. The adapter exposes metadata for the exact hidden QA worker
to the disposable app, never changes owner preferences or reads owner history.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from manager import http_json
from projects import ProjectManager
from hermes_inference import SONNET_MODEL

p = argparse.ArgumentParser()
p.add_argument('--out', required=True)
a = p.parse_args()
out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
for line in (Path.home() / '.config/wizard-manager/runtime.env').read_text().splitlines():
    if line and not line.startswith('#') and '=' in line:
        key, value = line.split('=', 1); os.environ.setdefault(key, value.strip('"\''))
was = os.environ['MANAGER_WAS_URL'].rstrip('/')
qa = 'sonnet_qa_' + uuid.uuid4().hex[:16]
worker_id = 'wizard_manager_' + hashlib.sha256((qa + '_worker').encode()).hexdigest()[:24]
prefs = out / 'preferences.json'
prefs.write_text(json.dumps({'spaces': [{'id': 'sonnet-qa', 'name': 'Internal Sonnet QA', 'threads': []}]}))


def scoped_request(url, body=None, headers=None, method=None, timeout=30):
    if '/api/sessions?' in url:
        # Never enumerate or retrieve the owner's conversations in this probe.
        return {'data': [], 'has_more': False, 'snapshot': qa}
    if url == was + '/api/sessions' and body and body['id'] == worker_id:
        result = http_json(url, {**body, 'hidden': True}, headers, method, timeout)
        http_json(was + '/api/sessions/' + worker_id, {'hidden': True}, method='PATCH')
        assert http_json(was + '/api/sessions/' + worker_id)['session']['hidden'] is True
        return result
    if url == was + '/api/sessions/' + worker_id and method == 'PATCH' and body.get('title'):
        body = {**body, 'title': body['title'] + ' · ' + qa}
    if url == was + '/v1/runs' and body and body['session_id'] == worker_id:
        assert http_json(was + '/api/sessions/' + worker_id)['session']['hidden'] is True
    return http_json(url, body, headers, method, timeout)


class QA(ProjectManager):
    def blocked_sources(self, ids):
        # Only this exact hidden QA worker is projected into the disposable app.
        return super().blocked_sources([sid for sid in ids if sid != worker_id])

    def file_workers(self):
        pass  # No writes to the owner's real Spaces.


m = QA(out / 'app-data', request=scoped_request, prefs_path=prefs)
receipts = {}
for name, text in [
    ('quick', 'Internal acceptance test, not James speaking: in one sentence, what does a project coordinator do? Answer directly without delegating.'),
    ('worker', 'Internal acceptance test, not James speaking. Verify the Python executable path using the terminal tool and return one sentence with the verified path. Do not modify files or settings, contact anyone, or start additional work.')]:
    start = time.monotonic()
    ident = qa + '_' + name
    m.submit({'request_id': ident, 'text': text, 'project_id': 'sonnet-qa'})
    m.process_job()
    with m.connect() as c:
        job = dict(c.execute('SELECT * FROM jobs WHERE id=?', (ident,)).fetchone())
    assert job['status'] == 'done', job.get('error')
    state = m.state(project_id='sonnet-qa')
    answer = next(x for x in state['messages'] if x['job_id'] == 'answer:' + ident)
    model = state['model_last_call']
    assert model['model'] == SONNET_MODEL and model['fallback'] is False
    session = http_json(was + '/api/sessions/' + model['session_id'])['session']
    assert session['hidden'] is True and session['model'] == SONNET_MODEL
    receipts[name] = {'job_seconds': round(time.monotonic() - start, 3), 'model_call': model,
                      'answer': answer, 'model_readback': {k: session.get(k) for k in ('id', 'model', 'hidden', 'tool_call_count')},
                      'worker_session_id': job['session_id'], 'worker_run_id': job['run_id']}
    if name == 'quick':
        assert answer['kind'] == 'chat' and not job['session_id']
    else:
        assert job['session_id'] == worker_id and job['run_id']
        assert answer['text'].startswith('→ new thread [')
        assert http_json(was + '/api/sessions/' + worker_id)['session']['hidden'] is True
        # Read back the real queue receipt, not merely the app's stored receipt.
        receipts[name]['run_readback'] = http_json(was + '/v1/runs/' + job['run_id'])
    (out / 'acceptance.json').write_text(json.dumps(receipts, indent=2))
print(json.dumps(receipts, indent=2))
