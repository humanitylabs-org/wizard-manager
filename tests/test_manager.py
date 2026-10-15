import json
import tempfile
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from manager import Manager, Problem, MODEL


class FakeAPI:
    """Deterministic isolated fixtures, never used as production evidence."""
    def __init__(self):
        self.calls = []
        self.sessions = []
        self.messages = []
        self.output = '{"action":"reply","text":"Hello."}'
        self.fail = False
        self.response_model = MODEL

    def __call__(self, url, body=None, headers=None, method=None, timeout=30):
        self.calls.append((url, body, headers, method))
        if url == 'http://model':
            if self.fail:
                raise RuntimeError('simulated offline')
            return {'model': self.response_model, 'choices': [{'message': {'content': self.output}}]}
        if '/messages?' in url:
            return {'data': self.messages, 'has_more': False}
        if '/api/sessions?' in url:
            return {'data': self.sessions, 'has_more': False, 'snapshot': 'fixture'}
        if url.endswith('/v1/runs'):
            return {'run_id': 'fixture-run', 'status': 'queued'}
        return {'id': (body or {}).get('id', 'fixture')}


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.api = FakeAPI()
        self.m = Manager(self.temp.name, was='http://was', model_url='http://model', key='fixture-only', request=self.api)
        with self.m.connect() as c:
            c.execute("UPDATE settings SET value='0' WHERE key='since'")

    def tearDown(self):
        self.temp.cleanup()

    def send(self, text='Hello', ident='request_0001', reply_to=None):
        return self.m.submit({'text': text, 'request_id': ident, 'reply_to': reply_to})

    def ready(self):
        self.api.sessions = [{'id': 'wizard_fixture', 'title': 'Fixture task', 'wizard_last_assistant_at': 20,
            'wizard_last_run_status': 'completed', 'wizard_attention': {'state': 'done', 'ask': 'Fixture completed'}}]
        self.api.messages = [{'id': 2, 'role': 'assistant', 'content': 'Fixture completed.', 'finish_reason': 'stop', 'timestamp': 20}]
        self.api.output = 'Fixture completed. Nothing needed.'

    def test_reply_persists(self):
        self.send()
        self.m.process_job()
        other = Manager(self.temp.name, request=self.api)
        self.assertEqual(other.state()['messages'][-1]['text'], 'Hello.')
        self.assertEqual(other.state()['jobs'], [])

    def test_send_idempotency(self):
        self.send(); self.send(); self.m.process_job(); self.m.process_job()
        self.assertEqual(len(self.m.state()['messages']), 2)

    def test_idempotency_conflict(self):
        self.send()
        with self.assertRaises(Problem):
            self.send('Different message')

    def test_pause_refuses_and_stops_calls(self):
        self.m.configure({'enabled': False})
        with self.assertRaises(Problem):
            self.send()
        self.m.scan(); self.m.summarize(); self.m.process_job()
        self.assertEqual(self.api.calls, [])
        self.assertFalse(Manager(self.temp.name).enabled())

    def test_pause_retains_queued_request(self):
        self.send(); self.m.configure({'enabled': False}); self.m.process_job()
        self.assertEqual(self.m.state()['jobs'][0]['status'], 'queued')
        self.m.configure({'enabled': True}); self.m.process_job()
        self.assertEqual(self.m.state()['jobs'], [])

    def test_invalid_routing_has_no_side_effect(self):
        self.api.output = '{"action":"delegate","session_id":"made-up-id"}'
        self.send('Build it'); self.m.process_job()
        self.assertEqual(self.m.state()['jobs'][0]['status'], 'failed')
        self.assertFalse(any(c[0].endswith('/v1/runs') for c in self.api.calls))

    def test_new_dispatch_is_durable_and_real_receipt(self):
        self.api.output = '{"action":"delegate","title":"Fixture task"}'
        self.send('Investigate a fixture'); self.m.process_job()
        s = self.m.state()
        self.assertEqual(s['messages'][-1]['kind'], 'delegation')
        calls = [c for c in self.api.calls if c[0].endswith('/v1/runs')]
        self.assertEqual(calls[0][2]['Idempotency-Key'], 'manager-request_0001')
        with self.m.connect() as c:
            row = c.execute('SELECT * FROM jobs').fetchone()
            self.assertEqual(row['run_id'], 'fixture-run')
            self.assertIsNotNone(row['plan'])

    def test_ready_once_across_restart(self):
        self.ready(); self.m.scan(); self.m.summarize(); self.m.scan()
        m2 = Manager(self.temp.name, was='http://was', model_url='http://model', key='fixture-only', request=self.api)
        m2.scan(); m2.summarize()
        self.assertEqual(len(m2.state()['messages']), 1)
        self.assertEqual(m2.state()['messages'][0]['source_message'], '2')

    def test_backlog_multiple_responses_preserved(self):
        self.ready()
        self.api.messages.insert(0, {'id': 1, 'role': 'assistant', 'content': 'Earlier fixture final.', 'finish_reason': 'stop', 'timestamp': 10})
        self.m.scan(); self.m.summarize(); self.m.summarize()
        self.assertEqual(len(self.m.state()['messages']), 2)

    def test_active_worker_not_ready(self):
        self.ready(); self.api.sessions[0]['status'] = 'running'; self.m.scan()
        self.assertEqual(self.m.state()['monitor']['pending'], 0)

    def test_private_and_hidden_excluded(self):
        self.ready(); self.api.sessions[0]['agent'] = {'id': 'private'}; self.m.scan()
        self.assertEqual(self.m.state()['monitor']['pending'], 0)

    def test_tool_intermediate_not_summarised(self):
        self.ready(); self.api.messages[0]['finish_reason'] = 'tool_calls'; self.m.scan()
        self.assertEqual(self.m.state()['monitor']['pending'], 0)

    def test_reply_target_routes_without_model(self):
        self.ready(); self.m.scan(); self.m.summarize()
        mid = self.m.state()['messages'][0]['id']
        before = self.m.model_calls
        self.send('Please explain the result', reply_to=mid); self.m.process_job()
        self.assertEqual(self.m.model_calls, before)
        self.assertEqual(self.m.state()['messages'][-1]['source_id'], 'wizard_fixture')

    def test_invalid_reply_target(self):
        with self.assertRaises(Problem):
            self.send(reply_to=543)

    def test_model_outage_retains_user_message_retry(self):
        self.api.fail = True; self.send(); self.m.process_job()
        self.assertEqual(self.m.state()['jobs'][0]['status'], 'failed')
        self.api.fail = False; self.m.retry({'request_id': 'request_0001'}); self.m.process_job()
        self.assertEqual(len(self.m.state()['messages']), 2)

    def test_wrong_model_refused(self):
        self.api.response_model = 'unapproved-fallback'; self.send(); self.m.process_job()
        self.assertEqual(self.m.state()['jobs'][0]['status'], 'failed')

    def test_summary_failure_has_durable_retry(self):
        self.ready(); self.m.scan(); self.api.fail = True; self.m.summarize()
        self.assertEqual(self.m.state()['monitor']['pending'], 1)
        self.assertEqual(self.m.state()['messages'], [])

    def test_restart_recovers_interrupted_jobs(self):
        self.send()
        with self.m.connect() as c:
            c.execute("UPDATE jobs SET status='working'")
        m2 = Manager(self.temp.name, was='http://was', model_url='http://model', key='fixture-only', request=self.api)
        m2.process_job()
        self.assertEqual(m2.state()['messages'][-1]['text'], 'Hello.')


if __name__ == '__main__':
    unittest.main()
