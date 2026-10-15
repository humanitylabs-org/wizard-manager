"""Global queue reports never infer totals from sampled conversation histories."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from manager import Manager, MODEL

QUESTION = "I'm curious, check our running threads. Are they all running or are some of them in a queue? How many can run simultaneously? How many are queued?"


class OperationalTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict('os.environ', {'MANAGER_READY_DB': ''})
        env.start(); self.addCleanup(env.stop)
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.calls = []
        self.route = True
        self.health = {'queue': {'max_active': 12, 'active': 9, 'queued': 2,
                                 'dispatch_paused': False, 'liveness_available': True}}
        self.m = Manager(tmp.name, was='http://was/wizard/hermes', model_url='http://model', key='fixture', request=self.request)
        self.m.cache = [{'id': 'stale', 'title': 'Old running work', 'status': 'running'}]
        self.m.cache_at = 1

    def request(self, url, body=None, headers=None, method=None, timeout=30):
        self.calls.append((url, body, method, timeout))
        if url == 'http://model':
            if 'operational_status' in body['messages'][0]['content']:
                content = {'operational_status': self.route}
            else:
                content = {'action': 'delegate', 'text': '', 'session_id': None, 'title': 'Queue fix'}
            return {'model': MODEL, 'choices': [{'message': {'content': json.dumps(content)}}]}
        self.assertIsNone(body); self.assertIsNone(method)
        self.assertEqual(url, 'http://was/wizard/health')
        self.assertLessEqual(timeout, 4)
        if isinstance(self.health, Exception):
            raise self.health
        return self.health

    def plan(self, text=QUESTION):
        self.m.submit({'text': text, 'request_id': 'queue_test_request'})
        with self.m.connect() as c:
            job = dict(c.execute('SELECT * FROM jobs').fetchone())
        return self.m.plan(job)

    def test_original_question_single_health_read_no_histories(self):
        result = self.plan()
        self.assertEqual(result['action'], 'reply')
        self.assertIsNone(result['session_id'])
        self.assertIn('9 active slots', result['text'])
        self.assertIn('2 queued requests', result['text'])
        self.assertIn('12 simultaneous', result['text'])
        self.assertEqual([c[0] for c in self.calls], ['http://model', 'http://was/wizard/health'])
        self.assertNotIn('request_text', result)

    def test_unavailable_does_not_fall_back_to_stale_inventory(self):
        self.health = TimeoutError('private URL or credential must not appear')
        result = self.plan()
        self.assertIn('unavailable', result['text'])
        self.assertNotIn('0', result['text'])
        self.assertNotIn('private URL', result['text'])
        self.assertEqual(result['operational_status']['error']['kind'], 'timeout')

    def test_incomplete_or_invalid_queue_never_defaults_to_zero(self):
        for bad in ({}, {'queue': {}}, {'queue': {**self.health['queue'], 'active': True}},
                    {'queue': {**self.health['queue'], 'queued': -1}},
                    {'queue': {**self.health['queue'], 'dispatch_paused': 'false'}}):
            with self.subTest(bad=bad):
                self.health = bad
                result = self.m.queue_status_plan()
                self.assertEqual(result['operational_status']['state'], 'unavailable')
                self.assertNotIn('0 active', result['text'])

    def test_paused_and_liveness_unknown_are_explicit(self):
        self.health['queue'].update(dispatch_paused=True, liveness_available=False)
        result = self.plan()
        self.assertIn('paused', result['text'])
        self.assertIn('liveness is unavailable', result['text'])
        self.assertIn('not verified running', result['text'])

    def test_zero_is_reported_only_when_observed(self):
        self.health['queue'].update(active=0, queued=0)
        result = self.plan()
        self.assertIn('0 active slots', result['text'])
        self.assertIn('0 queued requests', result['text'])

    def test_execution_request_not_hijacked_by_queue_word(self):
        self.route = False
        result = self.plan('Ask Astra to fix the queue capacity bug.')
        self.assertEqual(result['action'], 'delegate')
        self.assertFalse(any(c[0].endswith('/health') for c in self.calls))
        self.assertIn('Ask Astra to fix the queue capacity bug.', result['request_text'])


if __name__ == '__main__':
    unittest.main()
