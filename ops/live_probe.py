"""Explicit opt-in live acceptance probe: uses the real configured routes.
Run on the host with deployment env loaded. Writes into a separate QA data dir.
The only worker request is a clearly-labelled, read-only Manager acceptance check.
"""
import argparse
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from manager import Manager

p = argparse.ArgumentParser()
p.add_argument('--data', required=True)
p.add_argument('--out', required=True)
a = p.parse_args()
m = Manager(a.data)
result = {}
t = time.monotonic()
rows = m.sessions(fresh=True)
result['inventory'] = {'count': len(rows), 'seconds': round(time.monotonic() - t, 3)}
for ident, text in [
    ('manager_acceptance_greeting', 'This is a technical acceptance test, not James speaking. Reply briefly explaining what the Manager does. Do not delegate this message.'),
    ('manager_acceptance_dispatch', 'This is a technical acceptance test, not James speaking. Please delegate a bounded read-only task to a new thread titled Manager QA: use a terminal tool to print the Python executable path, then return one short sentence with the verified result. Do not change files, settings or contact anyone. Mark the response done with no action needed.')
]:
    t = time.monotonic()
    m.submit({'request_id': ident, 'text': text})
    m.process_job()
    with m.connect() as c:
        job = dict(c.execute('SELECT * FROM jobs WHERE id=?', (ident,)).fetchone())
    result[ident] = {'seconds': round(time.monotonic() - t, 3), 'status': job['status'], 'session_id': job['session_id'], 'run_id': job['run_id'], 'error': job['error']}
result['messages'] = m.state()['messages']
Path(a.out).write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
