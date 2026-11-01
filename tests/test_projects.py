"""Project Chats unit fixtures; no model, canonical data, or live writes."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from projects import ProjectManager
from manager import Problem
from test_manager import FakeAPI, FakeReadySource


class ScopedReady(FakeReadySource):
    def read(self, after, limit=1000, allowed=None):
        events, cursor, more = super().read(after, limit)
        return [e for e in events if allowed is None or e['session_id'] in allowed], cursor, more


class ProjectTests(unittest.TestCase):
    def setUp(self):
        from model_fixture import install_model_fixture
        install_model_fixture(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.prefs = self.root / 'ui-preferences.json'
        self.spaces = [{'id': 'alpha', 'name': 'Alpha', 'threads': ['work_alpha']},
                       {'id': 'beta', 'name': 'Beta', 'threads': ['work_beta']},
                       {'id': 'private', 'name': 'Private', 'threads': ['never_read'], 'agent': 'private'}]
        self.save()
        self.api = FakeAPI()
        self.api.sessions = [{'id': 'work_alpha', 'title': 'Alpha task', 'status': 'idle'},
                             {'id': 'work_beta', 'title': 'Beta task', 'status': 'idle'}]
        self.ready = ScopedReady()
        self.env = patch.dict('os.environ', {'WIZARD_ROUTER_KEY': 'fixture', 'MANAGER_MODEL_URL': 'http://model', 'MANAGER_WAS_URL': 'http://was'})
        self.env.start(); self.addCleanup(self.env.stop)
        self.m = self.open()
        self.m.sessions(fresh=True)

    def save(self):
        self.prefs.write_text(json.dumps({'spaces': self.spaces}))

    def open(self):
        return ProjectManager(self.root / 'data', request=self.api, ready_source=self.ready, prefs_path=self.prefs)

    def send(self, text='Hello', pid='alpha', ident='fixture_request', **kwargs):
        self.m.submit({'text': text, 'project_id': pid, 'request_id': ident, **kwargs})
        self.m.process_job()
        with self.m.connect() as c:
            return dict(c.execute('SELECT * FROM jobs WHERE id=?', (ident,)).fetchone())

    def test_worker_context_scoped_revalidated_and_never_reads_other_sources(self):
        self.ready.add(sid='work_alpha'); self.m.scan(); self.m.summarize()
        msg = self.m.state(project_id='alpha')['messages'][0]
        calls = []
        def latest(sid):
            calls.append(sid)
            return {'text': '## Full real report', 'attention': {'state': 'done'}, 'source_message': 'fixture'}
        self.ready.latest_response = latest
        result = self.m.worker_context('alpha', msg['id'])
        self.assertEqual(result['text'], '## Full real report')
        self.assertEqual(result['source_id'], 'work_alpha')
        self.assertEqual(calls, ['work_alpha'])
        for project, ident in [('beta', msg['id']), ('alpha', 99999)]:
            with self.assertRaises(Problem): self.m.worker_context(project, ident)
        self.api.sessions[0]['private'] = True
        with self.assertRaises(Problem): self.m.worker_context('alpha', msg['id'])
        self.assertEqual(calls, ['work_alpha'])
        self.api.sessions[0].pop('private')
        self.spaces[0]['threads'] = []; self.save()
        with self.assertRaises(Problem): self.m.worker_context('alpha', msg['id'])
        self.assertEqual(calls, ['work_alpha'])

    def test_worker_context_discards_a_report_after_space_move(self):
        self.ready.add(sid='work_alpha'); self.m.scan(); self.m.summarize()
        msg = self.m.state(project_id='alpha')['messages'][0]
        def moved(sid):
            self.spaces[0]['threads'] = []; self.save()
            return {'text': 'Must not escape', 'attention': {}, 'source_message': 'fixture'}
        self.ready.latest_response = moved
        with self.assertRaises(Problem): self.m.worker_context('alpha', msg['id'])

    def test_seed_resync_rename_remove_and_unsorted(self):
        self.assertEqual([p['name'] for p in self.m.project_list()], ['Alpha', 'Beta', 'Unsorted'])
        self.spaces[0]['name'] = 'Renamed'
        self.spaces.pop(1)
        self.save(); self.m.sync_projects()
        self.assertEqual([p['name'] for p in self.m.project_list()], ['Renamed', 'Unsorted'])
        self.assertIsNone(self.m.project_for_session('never_read'))

    def test_unread_and_history_are_per_project(self):
        self.ready.add(sid='work_alpha')
        self.m.scan(); self.m.summarize()
        a = self.m.state(project_id='alpha')
        b = self.m.state(project_id='beta')
        self.assertEqual(len(a['messages']), 1)
        self.assertEqual(b['messages'], [])
        self.assertEqual(next(p for p in a['projects'] if p['id'] == 'alpha')['unread'], 1)
        self.m.mark_read({'project_id': 'alpha', 'through': a['messages'][0]['id']})
        self.assertEqual(next(p for p in self.m.project_list() if p['id'] == 'alpha')['unread'], 0)

    def test_ready_dedupes_after_restart(self):
        self.ready.add(sid='work_alpha')
        self.m.scan(); self.m.summarize()
        self.m = self.open(); self.m.scan(); self.m.summarize()
        self.assertEqual(len(self.m.state(project_id='alpha')['messages']), 1)
        self.assertEqual(next(p for p in self.m.project_list() if p['id'] == 'alpha')['unread'], 1)

    def test_unowned_worker_not_ingested(self):
        self.api.sessions.append({'id': 'outside', 'title': 'Outside'})
        self.ready.add(sid='outside')
        self.m.scan(); self.m.summarize()
        self.assertFalse(any(self.m.state(project_id=p)['messages'] for p in ['alpha', 'beta', 'unsorted']))

    def test_answer_route_is_direct(self):
        job = self.send()
        self.assertEqual(job['status'], 'done')
        self.assertIsNone(job['session_id'])
        self.assertEqual(self.m.state(project_id='beta')['messages'], [])

    def test_continue_route_is_project_scoped_and_visible(self):
        self.api.output = '{"action":"delegate","session_id":"work_alpha","title":"wrong model title"}'
        job = self.send('Make the requested change')
        self.assertEqual(job['session_id'], 'work_alpha')
        msg = self.m.state(project_id='alpha')['messages'][-1]
        self.assertIn('→ continuing [Alpha task](/wizard-os-home/?session=work_alpha)', msg['text'])

    def test_new_thread_correction_overrides_reply_target(self):
        self.ready.add(sid='work_alpha'); self.m.scan(); self.m.summarize()
        target = self.m.state(project_id='alpha')['messages'][0]['id']
        job = self.send('no, new thread', reply_to=target)
        self.assertEqual(job['status'], 'done')
        self.assertNotEqual(job['session_id'], 'work_alpha')
        self.assertIn('→ new thread ', self.m.state(project_id='alpha')['messages'][-1]['text'])
        self.assertIn(job['session_id'], self.m.members('alpha'))

    def test_cross_project_worker_choice_rejected(self):
        self.api.output = '{"action":"delegate","session_id":"work_beta","title":"Beta"}'
        self.assertEqual(self.send('Do a task')['status'], 'failed')
        self.assertEqual(len(self.api.receipts), 0)

    def test_cross_project_reply_and_request_reuse_rejected(self):
        self.ready.add(sid='work_alpha'); self.m.scan(); self.m.summarize()
        target = self.m.state(project_id='alpha')['messages'][0]['id']
        with self.assertRaises(Problem):
            self.send(pid='beta', reply_to=target)
        self.send()
        with self.assertRaises(Problem):
            self.send(pid='beta')

    def test_context_never_contains_other_project(self):
        self.send('Alpha private planning', ident='fixture_first')
        self.send('Beta planning', pid='beta', ident='fixture_second')
        calls = [body for url, body, _, _ in self.api.calls if url == 'http://model']
        self.assertNotIn('Alpha private planning', calls[-1]['messages'][-1]['content'])

    def test_compact_index_no_transcript_calls(self):
        self.api.sessions[0]['status'] = 'running'
        self.api.sessions[0]['latest_message'] = {'content': 'must not be retained'}
        self.m.sessions(fresh=True)
        index = self.m.project_index('alpha')
        self.assertEqual(index[0]['state'], 'running')
        self.assertNotIn('must not be retained', json.dumps(index))
        self.assertNotIn('latest_message', self.m.cache[0])
        self.assertFalse(any('/messages?' in call[0] for call in self.api.calls))

    def test_recording_and_messenger_ids_rejected(self):
        self.assertFalse(self.m.safe_worker('wizard_private_recording_fixture'))
        self.assertFalse(self.m.safe_worker('messenger_fixture'))

    def test_read_watermark_cannot_consume_future_updates(self):
        self.m.mark_read({'project_id': 'alpha', 'through': 999999})
        self.ready.add(sid='work_alpha'); self.m.scan(); self.m.summarize()
        self.assertEqual(next(p for p in self.m.project_list() if p['id'] == 'alpha')['unread'], 1)

    def test_named_correction_routes_to_named_worker(self):
        self.assertEqual(self.send('No, continue Alpha task')['session_id'], 'work_alpha')

    def test_prefs_failure_preserves_last_projects(self):
        self.prefs.write_text('invalid')
        self.m.sync_projects()
        self.assertEqual(len(self.m.project_list()), 3)
        self.assertTrue(self.m.spaces_error)


if __name__ == '__main__':
    unittest.main()
