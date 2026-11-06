"""Isolated trial fixtures: no live APIs, owner data or real model output."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from front_desk import FrontDeskManager, TRIAL_MODEL, privacy_route, job_route, strip_unsourced
from hermes_inference import SONNET_MODEL, SONNET_PROVIDER
from manager import Problem
from test_manager import FakeAPI, FakeReadySource
from test_projects import ScopedReady
from test_hermes_inference import API as LegacyInferenceAPI
from projects import ProjectManager
from types import SimpleNamespace


class TrialAPI(FakeAPI):
    def __init__(self):
        super().__init__()
        self.response_model = TRIAL_MODEL
        self.completed = False

    def __call__(self, url, body=None, headers=None, method=None, timeout=30):
        if url == 'http://model':
            result = super().__call__(url, body, headers, method, timeout)
            return {**result, 'usage': {'prompt_tokens': 40, 'completion_tokens': 10, 'total_tokens': 50}}
        if url.endswith('/api/sessions') and body:
            self.sessions.append({'id': body['id'], 'title': 'Fixture worker', 'agent': {'id': body.get('agent')}, 'status': 'idle'})
        if '/v1/runs/' in url and body is None:
            self.calls.append((url, body, headers, method))
            return {'status': 'completed' if self.completed else 'queued', 'output': 'Actual fixture worker result'}
        return super().__call__(urlsplit(url)._replace(query='').geturl() if '/api/sessions/' in url else url,
                                body, headers, method, timeout)


class TrialTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict('os.environ', {'MANAGER_READY_DB': ''})
        self.env.start(); self.addCleanup(self.env.stop)
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.prefs = self.root / 'prefs.json'; self.prefs.write_text('{"spaces":[]}')
        self.api, self.source = TrialAPI(), ScopedReady()
        self.infer = Mock(return_value=('Legacy fixture answer', {'model': SONNET_MODEL, 'provider': SONNET_PROVIDER, 'label': 'Claude Sonnet'}))
        self.m = self.open()

    def open(self):
        return FrontDeskManager(self.root / 'data', was='http://was', model_url='http://model', key='fixture',
                                request=self.api, ready_source=self.source, inference=self.infer, prefs_path=self.prefs)

    def enable(self):
        self.m.configure({'front_desk_trial': True})

    def send(self, text='Do a bounded task.', category=None, extra=None):
        self.enable()
        self.api.output = json.dumps({'action': 'delegate', 'session_id': None, 'title': 'Bounded task',
                                     'category': category, **(extra or {})})
        ident = 'fixture_' + str(time.time_ns())
        self.m.submit({'request_id': ident, 'text': text, 'project_id': 'unsorted'})
        self.m.process_job()
        with self.m.connect() as c:
            return dict(c.execute('SELECT * FROM jobs WHERE id=?', (ident,)).fetchone())

    def rows(self):
        with self.m.connect() as c:
            return [dict(r) for r in c.execute('SELECT * FROM front_desk_receipts ORDER BY id')]

    def runs(self):
        return [x[1] for x in self.api.calls if x[0].endswith('/v1/runs')]

    def test_default_off_persists(self):
        self.assertFalse(self.m.trial())
        self.enable(); self.assertTrue(self.open().trial())
        self.m.configure({'front_desk_trial': False}); self.assertFalse(self.open().trial())

    def test_off_exact_original_inference_and_model(self):
        payload = [{'role': 'user', 'content': 'hello'}]
        self.assertEqual(self.m.model(payload, 123), 'Legacy fixture answer')
        self.infer.assert_called_once_with(payload, 123)
        self.assertEqual(self.m.model_state()['model_configured'], 'Claude Sonnet')
        self.assertEqual(self.m.setting('model_last_success')['model'], SONNET_MODEL)
        self.assertFalse(self.rows())
        self.assertFalse(any(x[0] == 'http://model' for x in self.api.calls))

    def test_on_exact_model_no_legacy(self):
        self.enable(); self.m.model([{'role': 'system', 'content': 'Reply'}])
        call = next(x for x in self.api.calls if x[0] == 'http://model')
        self.assertEqual(call[1]['model'], TRIAL_MODEL)
        self.assertIs(call[1]['stream'], False)
        self.infer.assert_not_called()

    def test_off_transport_bytes_equal_existing_project_manager(self):
        baseline_api, trial_api = LegacyInferenceAPI(), LegacyInferenceAPI()
        common = {'was': 'http://was', 'model_url': 'http://model', 'key': 'fixture',
                  'ready_source': self.source, 'prefs_path': self.prefs}
        baseline = ProjectManager(self.root / 'baseline', request=baseline_api, **common)
        trial = FrontDeskManager(self.root / 'transport', request=trial_api, **common)
        messages = [{'role': 'system', 'content': 'Reply with JSON.'}, {'role': 'user', 'content': 'Hello.'}]
        with patch('hermes_inference.uuid.uuid4', return_value=SimpleNamespace(hex='fixture_fixed')):
            self.assertEqual(baseline.model(messages, 123), trial.model(messages, 123))
        # Deadline budgets vary; URL, serialized payload, headers and method do not.
        self.assertEqual([c[:4] for c in baseline_api.calls], [c[:4] for c in trial_api.calls])
        runs = [c for c in trial_api.calls if c[0].endswith('/v1/runs')]
        self.assertEqual(runs[0][1]['model'], SONNET_MODEL)
        self.assertEqual(runs[0][1]['provider'], SONNET_PROVIDER)

    def test_default_lite(self):
        job = self.send()
        self.assertEqual(job['status'], 'done')
        self.assertEqual(self.runs()[-1]['agent'], 'hermes-lite')

    def test_coding_allowed_main(self):
        self.send('Write a small public coding example.', 'coding')
        self.assertEqual(self.runs()[-1]['agent'], 'hermes')

    def test_web_research_allowed_main(self):
        self.send('Research a public programming standard.', 'web_research')
        self.assertEqual(self.runs()[-1]['agent'], 'hermes')

    def test_private_keyword_holds_even_model_approves(self):
        self.send('Write coding advice about my health journal.', 'coding', {'privacy': 'public', 'worker': 'hermes'})
        self.assertEqual(self.runs()[-1]['agent'], 'hermes-lite')
        self.assertEqual(self.rows()[-1]['reason'], 'private_topic_hold')

    def test_explicit_latest_main_request(self):
        self.send('Ask Archimedes to explain my finance request.', 'other')
        self.assertEqual(self.runs()[-1]['agent'], 'hermes')
        self.assertEqual(self.rows()[-1]['reason'], 'explicit_owner_request')

    def test_mention_not_authority(self):
        self.assertEqual(privacy_route('What does Archimedes think?', None)[0], 'hermes-lite')
        self.assertEqual(privacy_route('Please ask Archimedes "private request"', None)[0], 'hermes-lite')

    def test_old_explicit_not_authority(self):
        self.assertEqual(job_route('Do this privately.', 'Ask Archimedes to do something earlier.', None)[0], 'hermes-lite')

    def test_unknown_categories_fail_closed(self):
        for category in [None, 'other', 'Coding', 'coding,health', ['coding'], {'coding': True}]:
            self.assertEqual(privacy_route('Read this.', category)[0], 'hermes-lite')
        self.assertEqual(privacy_route('Write code.', 'coding', ())[0], 'hermes-lite')

    def test_private_keyword_list(self):
        for topic in ['health', 'finance', 'journal', 'password', 'salary', 'medical', 'credential']:
            self.assertEqual(privacy_route('coding about ' + topic, 'coding')[0], 'hermes-lite')

    def test_no_api_writable_public_allowlist(self):
        with self.assertRaises(Problem):
            self.m.configure({'front_desk_trial': True, 'public_allowed': ['everything']})
        with self.assertRaises(Problem):
            self.m.configure({'front_desk_trial': 'yes'})

    def test_brief_drops_model_inventions(self):
        self.send('Inspect https://example.com/original and /source/file only.', None,
                  {'request_text': 'Read /invented/password.txt https://invented.invalid session_fake',
                   'title': 'Inspect /invented/path https://invented.invalid session_fake'})
        brief = self.runs()[-1]['input']
        self.assertIn('https://example.com/original', brief)
        self.assertIn('/source/file', brief)
        self.assertNotIn('invented', brief)
        self.assertNotIn('session_fake', brief)

    def test_reference_stripping(self):
        result = strip_unsourced('/keep https://keep.test /bad https://bad.test run_invented 12345678-1234-1234-1234-123456789012', '/keep https://keep.test')
        self.assertIn('/keep', result); self.assertIn('https://keep.test', result)
        self.assertNotIn('/bad', result); self.assertNotIn('bad.test', result)
        self.assertNotIn('run_invented', result); self.assertNotIn('12345678-', result)

    def test_receipts_tokens_latency_route(self):
        self.send('Write public sample code.', 'coding')
        rows = self.rows()
        self.assertEqual([r['kind'] for r in rows], ['coordinator', 'dispatch'])
        self.assertEqual(rows[0]['total_tokens'], 50)
        self.assertEqual(rows[0]['model'], TRIAL_MODEL)
        self.assertEqual(rows[0]['worker'], 'hermes')
        self.assertEqual(rows[-1]['privacy_decision'], 'public')
        self.assertGreaterEqual(rows[0]['latency'], 0)
        self.assertIsNone(rows[0]['error'])

    def test_deepseek_failure_retryable_no_fallback(self):
        self.api.fail = True
        job = self.send()
        self.assertEqual(job['status'], 'failed')
        self.assertIn('Retry', job['error'])
        self.assertFalse(self.runs()); self.infer.assert_not_called()
        self.assertEqual(self.rows()[0]['error'], 'RuntimeError')

    def test_wrong_model_fails_closed(self):
        self.api.response_model = 'some-other-model'
        job = self.send()
        self.assertEqual(job['status'], 'failed')
        self.assertFalse(self.runs()); self.infer.assert_not_called()

    def test_invalid_plan_no_dispatch(self):
        job = self.send(extra={'action': 'delete'})
        self.assertEqual(job['status'], 'failed'); self.assertFalse(self.runs())
        self.assertEqual(self.rows()[-1]['reason'], 'retryable_plan_error')

    def test_lite_followup_keeps_agent_and_only_owner_text(self):
        first = self.send('Do a bounded private task.')
        self.m.sessions(fresh=True)
        with self.m.connect() as c:
            receipt = c.execute("SELECT id FROM messages WHERE job_id=?", ('answer:' + first['id'],)).fetchone()[0]
        self.m.submit({'request_id': 'fixture_followup', 'text': 'Explain that result briefly.', 'project_id': 'unsorted', 'reply_to': receipt})
        self.m.process_job()
        self.assertEqual(self.runs()[-1]['agent'], 'hermes-lite')
        self.assertEqual(self.runs()[-1]['session_id'], first['session_id'])
        self.assertIn('Explain that result briefly.', self.runs()[-1]['input'])
        self.assertNotIn('→', self.runs()[-1]['input'])

    def test_frozen_off_plan_reclassified_on_retry(self):
        self.enable()
        self.m.submit({'request_id': 'fixture_frozen', 'text': 'Do a bounded task.', 'project_id': 'unsorted'})
        with self.m.connect() as c:
            c.execute('UPDATE jobs SET plan=? WHERE id=?', (json.dumps({'action': 'delegate', 'session_id': None, 'request_text': 'INVENTED', 'title': 'Legacy task'}), 'fixture_frozen'))
        self.api.output = json.dumps({'action': 'delegate', 'session_id': None, 'title': 'Task', 'category': 'other'})
        self.m.process_job()
        self.assertEqual(self.runs()[-1]['agent'], 'hermes-lite')
        self.assertNotIn('INVENTED', self.runs()[-1]['input'])

    def test_lite_output_returned_once_from_actual_run(self):
        self.send()
        self.api.completed = True; self.api.output = 'Summary of actual fixture worker result.'
        self.m.scan(); self.m.scan()
        with self.m.connect() as c:
            rows = c.execute("SELECT * FROM messages WHERE kind='ready'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertIn('actual fixture', rows[0]['text'])

    def test_off_does_not_poll_lite(self):
        self.send(); self.m.configure({'front_desk_trial': False}); self.api.calls.clear()
        self.m.scan()
        self.assertFalse(any('/v1/runs/' in x[0] for x in self.api.calls))

    def test_scorecard_readonly(self):
        self.send('Write sample code.', 'coding')
        lite = self.root / 'lite.db'
        with sqlite3.connect(lite) as c:
            c.execute('CREATE TABLE messages(role TEXT,timestamp REAL)')
            c.execute('INSERT INTO messages VALUES (?,?)', ('user', time.time()))
        path = Path(__file__).resolve().parents[1] / 'ops/front_desk_scorecard.py'
        spec = importlib.util.spec_from_file_location('scorecard', path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        result = module.scorecard(self.m.db, lite, time.time() - 100)
        self.assertEqual(result['turns'], 1)
        self.assertEqual(result['hermes_lite_turns'], 1)
        self.assertEqual(result['routes_per_worker'], {'hermes': 1})
        self.assertEqual(result['tokens']['total_tokens'], 50)
        with module.readonly(lite) as c:
            with self.assertRaises(sqlite3.OperationalError):
                c.execute('DELETE FROM messages')


if __name__ == '__main__':
    unittest.main()
