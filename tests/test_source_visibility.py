"""Visibility regressions. Synthetic canonical SQL + supported WAS fixtures only."""
import hashlib
import json
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from test_manager import FakeAPI, FakeReadySource, Manager, Problem
from ready_source import ReadySource


class SourceVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'canonical.sqlite3'
        with closing(sqlite3.connect(self.path)) as c, c:
            c.executescript('''CREATE TABLE sessions(id TEXT PRIMARY KEY, hidden INTEGER DEFAULT 0, archived INTEGER DEFAULT 0, parent_session_id TEXT);
            CREATE TABLE messages(id INTEGER PRIMARY KEY,message_uid TEXT);
            INSERT INTO sessions(id) VALUES ('hidden-later'),('archive-later'),('ordinary');''')
        self.api = FakeAPI()
        self.api.sessions = [{'id': sid, 'title': sid} for sid in ('hidden-later', 'archive-later', 'ordinary')]
        self.source = ReadySource(self.path)
        self.m = self.manager()
        with self.m.connect() as c:
            for sid in ('hidden-later', 'archive-later', 'ordinary'):
                c.execute("INSERT INTO messages(role,text,created,kind,source_id,title) VALUES ('assistant',?,0,'ready',?,?)", (sid + ' result', sid, sid))
            c.execute("INSERT INTO messages(role,text,created,kind,source_id) VALUES ('user','User-authored words remain',0,'chat','hidden-later')")

    def manager(self):
        return Manager(self.root / 'manager', was='http://was', model_url='http://model', key='fixture', request=self.api, ready_source=self.source)

    def flags(self, sid, **fields):
        with closing(sqlite3.connect(self.path)) as c, c:
            for key, value in fields.items():
                assert key in ('hidden', 'archived', 'parent_session_id')
                c.execute(f'UPDATE sessions SET {key}=? WHERE id=?', (value, sid))
        for s in self.api.sessions:
            if s['id'] == sid:
                s.update(fields)

    def event(self):
        with self.m.connect() as c:
            c.execute("INSERT INTO events(id,session_id,message_id,title,body,attention,created) VALUES ('fixture-event','hidden-later','fixture-msg','Hidden later','PRIVATE RESULT','{}',0)")

    def test_retrospective_projection_restart_archive_user_and_no_mutations(self):
        self.flags('hidden-later', hidden=1)
        self.flags('archive-later', archived=1)
        canonical_hash = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with self.m.connect() as c:
            original = [tuple(r) for r in c.execute('SELECT * FROM messages')]
        for manager in (self.m, self.manager()):
            state = manager.state()
            self.assertEqual([m['id'] for m in state['messages']], [2, 3, 4])
            self.assertEqual(state['suppressed_sources'], ['hidden-later'])
            self.assertEqual(manager.state(after=4)['suppressed_sources'], ['hidden-later'])
            self.assertEqual(state['next_after'], 4)
            self.assertFalse(state['has_more'])
        self.assertEqual(self.api.calls, [], 'polling must not contact WAS or models')
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), canonical_hash)
        with self.m.connect() as c:
            self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM messages')], original)

    def test_temporary_canonical_failure_is_fail_closed_and_reversible(self):
        with patch.object(self.source, 'blocked_sources', side_effect=OSError('fixture offline')):
            self.assertEqual([m['id'] for m in self.m.state()['messages']], [4])
            self.assertEqual(len(self.m.state(after=4)['suppressed_sources']), 3)
        self.assertEqual([m['id'] for m in self.m.state()['messages']], [1, 2, 3, 4])

    def test_hidden_after_ingestion_and_restart_never_enters_model(self):
        self.event()
        self.flags('hidden-later', hidden=1)
        other = self.manager()
        self.assertTrue(other.summarize())
        self.assertEqual(other.model_calls, 0)
        with other.connect() as c:
            self.assertEqual(c.execute('SELECT status FROM events').fetchone()[0], 'held')
            self.assertEqual(c.execute('SELECT count(*) FROM messages').fetchone()[0], 4)

    def test_failed_was_detail_never_uses_pending_body(self):
        self.event(); self.api.was_fail = True
        self.m.summarize()
        self.assertEqual(self.m.model_calls, 0)
        with self.m.connect() as c:
            self.assertEqual(c.execute('SELECT status FROM events').fetchone()[0], 'pending')
        self.api.was_fail = False
        with self.m.connect() as c:
            c.execute('UPDATE events SET retry_at=0')
        self.api.output = 'Ordinary fixture summary'
        self.m.summarize()
        self.assertEqual(self.m.model_calls, 1)

    def test_hidden_during_model_call_does_not_publish_result(self):
        self.event()
        def model(*args):
            self.flags('hidden-later', hidden=1)
            return 'Must not publish'
        self.m.model = model
        self.m.summarize()
        with self.m.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM messages').fetchone()[0], 4)
            self.assertEqual(c.execute('SELECT status FROM events').fetchone()[0], 'held')

    def test_hidden_history_cached_inventory_and_reply_target_are_excluded(self):
        self.m.sessions(fresh=True)
        with self.m.connect() as c:
            c.execute("UPDATE messages SET kind='delegation' WHERE id=1")
        self.m.submit({'text': 'Hello', 'request_id': 'request_fixture'})
        self.flags('hidden-later', hidden=1)
        self.assertNotIn('hidden-later', [s['id'] for s in self.m.thread_inventory()])
        self.m.process_job()
        content = json.loads(next(c[1] for c in self.api.calls if c[0] == 'http://model')['messages'][1]['content'])
        self.assertNotIn('hidden-later result', json.dumps(content))
        self.assertIn('User-authored words remain', json.dumps(content))
        self.assertNotIn('hidden-later', [s['id'] for s in content['work']])
        with self.assertRaises(Problem):
            self.m.submit({'text': 'Reply', 'request_id': 'request_reply', 'reply_to': 1})

    def test_reply_queued_before_hide_cannot_send_or_summarize_hidden_target(self):
        self.m.submit({'text': 'Continue this', 'request_id': 'request_reply', 'reply_to': 1})
        self.flags('hidden-later', hidden=1)
        self.m.process_job()
        self.assertEqual(self.m.model_calls, 0)
        self.assertFalse(any(c[0].endswith('/v1/runs') for c in self.api.calls))
        self.assertEqual(self.m.state()['jobs'][0]['status'], 'failed')

    def test_all_hidden_page_still_advances_past_it(self):
        with self.m.connect() as c:
            c.execute('DELETE FROM messages')
            c.executemany("INSERT INTO messages(role,text,created,source_id) VALUES ('assistant','fixture',0,'hidden-later')", [()] * 1000)
            c.execute("INSERT INTO messages(role,text,created) VALUES ('user','Keep this',0)")
        self.flags('hidden-later', hidden=1)
        page = self.m.state()
        self.assertEqual(page['messages'], [])
        self.assertTrue(page['has_more'])
        self.assertEqual(page['next_after'], 1000)
        self.assertEqual(self.m.state(after=page['next_after'])['messages'][0]['text'], 'Keep this')

    def test_was_only_background_checks_preserve_archive_and_fail_closed(self):
        self.m.ready_source = None
        self.flags('hidden-later', hidden=1)
        self.flags('archive-later', archived=1)
        self.assertEqual([m['id'] for m in self.m.state()['messages']], [4])
        self.assertEqual(self.api.calls, [])
        self.m.refresh_source_checks()
        self.assertEqual([m['id'] for m in self.m.state()['messages']], [2, 3, 4])
        self.api.was_fail = True
        self.m.refresh_source_checks()
        self.assertEqual([m['id'] for m in self.m.state()['messages']], [4])

    def test_legacy_frozen_context_is_rechecked_without_rewriting_payload(self):
        self.m.submit({'text': 'Continue this', 'request_id': 'request_legacy'})
        payload = self.m.relay_text('Continue this', [{'role':'assistant', 'source_id':'hidden-later', 'text':'Private result'}])
        plan = {'action':'delegate', 'title':'New work', 'request_text':payload}
        with self.m.connect() as c:
            c.execute('UPDATE jobs SET plan=?', (json.dumps(plan),))
        self.flags('hidden-later', hidden=1)
        self.m.process_job()
        self.assertEqual(self.m.model_calls, 0)
        self.assertEqual(self.api.calls, [])
        with self.m.connect() as c:
            saved = json.loads(c.execute('SELECT plan FROM jobs').fetchone()[0])
        self.assertEqual(saved, plan, 'never change an idempotent payload after acceptance')
        self.assertEqual(self.m.state()['jobs'][0]['status'], 'failed')

    def test_source_projection_has_a_fail_closed_bound(self):
        with self.m.connect() as c:
            c.executemany("INSERT INTO messages(role,text,created,source_id) VALUES ('assistant','fixture',0,?)", [('source-'+str(i),) for i in range(10001)])
        with patch.object(self.source, 'blocked_sources', side_effect=AssertionError('must not perform unbounded reads')):
            page = self.m.state()
        self.assertTrue(page['suppress_source_updates'])
        self.assertEqual([m['id'] for m in page['messages']], [4])
        self.assertEqual(page['suppressed_sources'], [])

    def test_missing_child_and_large_batches_are_read_only(self):
        self.flags('ordinary', parent_session_id='parent')
        ids = {'missing-' + str(i) for i in range(1200)} | {'ordinary', 'hidden-later', 'archive-later'}
        self.flags('archive-later', archived=1)
        self.assertEqual(self.source.blocked_sources(ids), ids - {'hidden-later', 'archive-later'})


if __name__ == '__main__':
    unittest.main()
