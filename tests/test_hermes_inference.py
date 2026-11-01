"""Inference transport regressions: never touches an agent or owner data."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from hermes_inference import HermesInference, InferenceFailure, SONNET_MODEL, SONNET_PROVIDER
from manager import Manager, Problem


class API:
    def __init__(self):
        self.calls = []
        self.hidden = True
        self.model = SONNET_MODEL
        self.status = 'completed'
        self.output = '{"action":"reply","text":"Hello"}'
        self.tool_count = 0
        self.fail_patch = False
        self.session_reads = 0
        self.hide_after_run = False

    def __call__(self, url, body=None, headers=None, method=None, timeout=30):
        self.calls.append((url, body, headers, method, timeout))
        if method == 'PATCH' and self.fail_patch:
            raise RuntimeError('private upstream body')
        if '/api/sessions/' in url and body is None:
            self.session_reads += 1
            return {'session': {'id': url.rsplit('/', 1)[-1], 'hidden': self.hidden,
                                'model': self.model, 'tool_call_count': self.tool_count}}
        if url.endswith('/v1/runs'):
            if self.hide_after_run:
                self.hidden = False
            return {'run_id': 'fixture-run'}
        if url.endswith('/v1/runs/fixture-run'):
            return {'status': self.status, 'output': self.output}
        return {}


class InferenceTests(unittest.TestCase):
    def setUp(self):
        self.api = API()
        self.infer = HermesInference('http://was', self.api, timeout=1)
        self.messages = [{'role': 'system', 'content': 'Return ONLY JSON.'},
                         {'role': 'user', 'content': 'Untrusted supplied project context.'}]

    def test_hidden_readback_precedes_admission_and_model_is_locked(self):
        text, receipt = self.infer(self.messages, 123)
        self.assertEqual(text, self.api.output)
        self.assertEqual(receipt['model'], SONNET_MODEL)
        self.assertFalse(receipt['fallback'])
        calls = self.api.calls
        self.assertEqual(calls[1][3], 'PATCH')
        self.assertEqual(calls[2][1], None)
        self.assertTrue(calls[3][0].endswith('/v1/runs'))
        self.assertEqual(calls[0][1]['source'], 'api_server')
        self.assertTrue(calls[0][1]['hidden'])
        for i in (0, 3):
            self.assertEqual(calls[i][1]['provider'], SONNET_PROVIDER)
            self.assertEqual(calls[i][1]['model'], SONNET_MODEL)
            self.assertIs(calls[i][1]['require_model_lock'], True)
        self.assertIn('Return ONLY JSON.', calls[3][1]['input'])
        self.assertIn('Untrusted supplied project context.', calls[3][1]['input'])
        self.assertIn('returning action=delegate', calls[3][1]['input'])
        self.assertEqual(calls[3][1]['model_options'], {'reasoning': {'enabled': False}})
        self.assertEqual(self.api.session_reads, 2)
        self.assertTrue(all(0 < c[4] <= 1 for c in calls))

    def test_each_call_has_its_own_session_and_idempotency_key(self):
        self.infer(self.messages); self.infer(self.messages)
        runs = [c for c in self.api.calls if c[0].endswith('/v1/runs')]
        self.assertNotEqual(runs[0][1]['session_id'], runs[1][1]['session_id'])
        self.assertNotEqual(runs[0][2], runs[1][2])

    def test_patch_failure_never_submits(self):
        self.api.fail_patch = True
        with self.assertRaises(RuntimeError):
            self.infer(self.messages)
        self.assertFalse(any(c[0].endswith('/v1/runs') for c in self.api.calls))

    def test_false_or_missing_hidden_never_submits(self):
        for flag in (False, None, 1):
            with self.subTest(flag=flag):
                self.api = API(); self.api.hidden = flag
                with self.assertRaises(InferenceFailure):
                    HermesInference('http://was', self.api)(self.messages)
                self.assertFalse(any(c[0].endswith('/v1/runs') for c in self.api.calls))

    def test_wrong_model_never_submits(self):
        self.api.model = 'deepseek-v4-1-flash'
        with self.assertRaises(InferenceFailure):
            self.infer(self.messages)
        self.assertFalse(any(c[0].endswith('/v1/runs') for c in self.api.calls))

    def test_completed_run_revalidates_hidden(self):
        self.api.hide_after_run = True
        with self.assertRaises(InferenceFailure):
            self.infer(self.messages)
        self.assertTrue(self.api.calls[-1][0].endswith('/stop'))

    def test_failed_run_cancels_no_fallback(self):
        self.api.status = 'failed'
        with self.assertRaises(InferenceFailure):
            self.infer(self.messages)
        self.assertTrue(self.api.calls[-1][0].endswith('/stop'))
        self.assertTrue(all(c[0].startswith('http://was/') for c in self.api.calls))

    def test_deadline_cancels_and_does_not_wait_forever(self):
        self.api.status = 'queued'
        # Deterministic monotonic clock avoids real waiting.
        with patch('hermes_inference.time.monotonic', side_effect=[i / 10 for i in range(100)]), patch('hermes_inference.time.sleep'):
            with self.assertRaises(TimeoutError):
                self.infer(self.messages)
        self.assertTrue(self.api.calls[-1][0].endswith('/stop'))
        self.assertEqual(self.api.calls[-1][4], 2)

    def test_empty_output_and_tool_results_refused(self):
        for output, tools in [('', 0), ('text', 1)]:
            self.api.output, self.api.tool_count = output, tools
            with self.assertRaises(InferenceFailure):
                self.infer(self.messages)

    def test_model_state_truthful_persistent_and_error_sanitized(self):
        with tempfile.TemporaryDirectory() as data, patch.dict('os.environ', {'MANAGER_READY_DB': ''}):
            m = Manager(data, inference=self.infer)
            self.assertEqual(m.model_state()['model_in_use'], 'Not used yet')
            m.model(self.messages)
            self.assertEqual(m.model_state()['model_in_use'], 'Claude Sonnet')
            self.assertEqual(Manager(data).model_state()['model'], SONNET_MODEL)
            self.api.fail_patch = True
            with self.assertLogs(level='WARNING') as logs, self.assertRaises(Problem):
                m.model(self.messages)
            state = m.model_state()
            self.assertIn('no fallback', state['model_error'])
            self.assertEqual(state['model_last_call']['model'], SONNET_MODEL)
            self.assertNotIn('private upstream', str(state))
            self.assertNotIn('private upstream', str(logs.output))
