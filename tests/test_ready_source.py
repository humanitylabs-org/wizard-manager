"""Canonical Ready evidence contract; all databases are tiny synthetic fixtures."""
import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from ready_source import ReadySource, attention


def tagged(body='Fixture completed.', state='done', ask='Fixture completed', **extra):
    value = {'state': state, 'ask': ask, **extra}
    return body + '\n[WIZARD_STATUS_V1]' + json.dumps(value) + '[/WIZARD_STATUS_V1]'


class ReadySourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'canonical.sqlite3'
        with closing(sqlite3.connect(self.path)) as c, c:
            c.executescript('''
                CREATE TABLE sessions (
                    id TEXT PRIMARY KEY, parent_session_id TEXT,
                    hidden INTEGER DEFAULT 0, archived INTEGER DEFAULT 0
                );
                CREATE TABLE messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                    role TEXT NOT NULL, content TEXT, timestamp REAL,
                    finish_reason TEXT, display_kind TEXT, tool_calls TEXT,
                    compacted INTEGER DEFAULT 0, message_uid TEXT
                );
                INSERT INTO sessions(id) VALUES ('wizard_fixture');
            ''')
        self.source = ReadySource(self.path)

    def session(self, sid, **fields):
        values = {'id': sid, **fields}
        with closing(sqlite3.connect(self.path)) as c, c:
            c.execute('INSERT INTO sessions (' + ','.join(values) + ') VALUES (' +
                      ','.join('?' for _ in values) + ')', tuple(values.values()))

    def row(self, **fields):
        values = {'session_id': 'wizard_fixture', 'role': 'assistant',
                  'content': tagged(), 'timestamp': 20, 'finish_reason': 'stop', **fields}
        with closing(sqlite3.connect(self.path)) as c, c:
            return c.execute('INSERT INTO messages (' + ','.join(values) + ') VALUES (' +
                             ','.join('?' for _ in values) + ')', tuple(values.values())).lastrowid

    def test_visible_final_requires_its_own_valid_marker(self):
        self.row(content='Historical helper handoff, all done.', finish_reason='stop')
        self.row(content='[WIZARD_STATUS_V1]{bad json}[/WIZARD_STATUS_V1]')
        self.row(content=tagged(state='running'))
        self.row(content=tagged(ask=''))
        self.row(role='user')
        self.row(role='tool')
        good = self.row(content=tagged('Real result.', state='check', ask='Review the result', title='Result'))
        events, cursor, more = self.source.read(0)
        self.assertEqual([e['id'] for e in events], [good])
        self.assertEqual(events[0]['body'], 'Real result.')
        self.assertEqual(events[0]['attention'], {'state': 'check', 'ask': 'Review the result', 'title': 'Result'})
        self.assertEqual(cursor, good)
        self.assertFalse(more)

    def test_hidden_and_nonfinal_display_kinds_and_tool_payloads_are_ignored(self):
        for kind in ('hidden', 'tool_call', 'tool_result', 'thinking', 'analysis', 'summary', 'status'):
            self.row(display_kind=kind)
        self.row(tool_calls='[{"name":"helper"}]', finish_reason='tool_calls')
        self.row(content='Helper handoff', finish_reason='tool_calls')
        visible = [self.row(display_kind=kind, tool_calls=tools)
                   for kind, tools in ((None, None), ('', ''), ('final', '[]'), ('final', 'null'))]
        events, _, _ = self.source.read(0)
        self.assertEqual([e['id'] for e in events], visible)

    def test_parent_hidden_archived_and_orphan_sessions_excluded(self):
        for sid, fields in [('child', {'parent_session_id': 'wizard_fixture'}),
                            ('hidden', {'hidden': 1}), ('archived', {'archived': 1})]:
            self.session(sid, **fields)
            self.row(session_id=sid)
        self.row(session_id='orphan')
        good = self.row()
        self.assertEqual([e['id'] for e in self.source.read(0)[0]], [good])

    def test_insertion_order_survives_timestamp_ties_and_regression(self):
        ids = [self.row(timestamp=stamp) for stamp in (20, 20, 5, 0)]
        events, cursor, _ = self.source.read(0)
        self.assertEqual([e['id'] for e in events], ids)
        self.assertEqual([e['created'] for e in events], [20, 20, 5, 0])
        self.assertEqual(cursor, ids[-1])
        self.assertEqual(self.source.read(cursor), ([], cursor, False))

    def test_compacted_retained_rows_remain_ready_evidence(self):
        first = self.row(compacted=1, timestamp=10)
        second = self.row(compacted=0, timestamp=20)
        self.assertEqual([e['id'] for e in self.source.read(0)[0]], [first, second])
        with closing(sqlite3.connect(self.path)) as c, c:
            c.execute('UPDATE messages SET compacted=1')
        self.assertEqual(self.source.read(second), ([], second, False))

    def test_pagination_advances_across_pages_without_valid_markers(self):
        self.row(content='untagged handoff')
        self.row(display_kind='hidden')
        good = self.row()
        last = self.row(content='untagged final')
        first, cursor, more = self.source.read(0, limit=2)
        self.assertEqual(first, [])
        self.assertEqual(cursor, 2)
        self.assertTrue(more)
        second, cursor, more = self.source.read(cursor, limit=2)
        self.assertEqual([e['id'] for e in second], [good])
        self.assertEqual(cursor, last)
        self.assertTrue(more)
        self.assertEqual(self.source.read(cursor, limit=2), ([], last, False))
        new = self.row(timestamp=1)
        self.assertEqual([e['id'] for e in self.source.read(cursor, limit=2)[0]], [new])

    def test_head_tracks_all_insertions_not_latest_timestamp(self):
        self.assertEqual(self.source.head(), 0)
        self.row(timestamp=100)
        last = self.row(role='user', timestamp=1)
        self.assertEqual(self.source.head(), last)

    def test_database_is_read_only_and_bytes_unchanged(self):
        self.row()
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        names = sorted(p.name for p in self.path.parent.iterdir())
        self.source.head()
        self.source.read(0)
        with closing(self.source.open()) as c:
            self.assertEqual(c.execute('PRAGMA query_only').fetchone()[0], 1)
            # query_only is an additional fence; mode=ro must still deny writes without it.
            c.execute('PRAGMA query_only=OFF')
            for sql in ('DELETE FROM messages', "UPDATE sessions SET hidden=1",
                        "INSERT INTO sessions(id) VALUES ('not-allowed')", 'CREATE TABLE forbidden(x)'):
                with self.subTest(sql=sql), self.assertRaises(sqlite3.OperationalError):
                    c.execute(sql)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), names)

    def test_missing_path_is_not_created(self):
        missing = self.path.parent / 'missing.sqlite3'
        with self.assertRaises(FileNotFoundError):
            ReadySource(missing)
        self.assertFalse(missing.exists())

    def test_missing_sessions_schema_fails_closed(self):
        with closing(sqlite3.connect(self.path)) as c, c:
            c.execute('DROP TABLE sessions')
        with self.assertRaises(sqlite3.OperationalError):
            self.source.read(0)

    def test_real_adapter_to_manager_holds_then_delivers_only_tagged_visible_rows(self):
        from manager import Manager, MODEL
        sessions, calls = [], []
        def api(url, body=None, headers=None, method=None, timeout=30):
            calls.append((url, body))
            if url == 'http://model':
                return {'model': MODEL, 'choices': [{'message': {'content': 'Review the fixture result.'}}]}
            if '/api/sessions?' in url:
                return {'data': list(sessions), 'has_more': False}
            if '/api/sessions/' in url:
                return {'session': next((s for s in sessions if s['id'] == url.rsplit('/', 1)[-1]), None)}
            raise AssertionError('Unexpected external request: ' + url)
        self.row(content=tagged('Old pre-opt-in result.'), message_uid='old-logical')
        manager = Manager(self.path.parent / 'manager', was='http://was', model_url='http://model',
                          key='fixture-only', request=api, ready_source=self.source)
        self.row(content=tagged('Old pre-opt-in result.'), message_uid='old-logical')
        self.row(content='Historical helper handoff, no status marker.')
        self.row(display_kind='hidden')
        self.session('child', parent_session_id='wizard_fixture')
        self.row(session_id='child')
        good = self.row(content=tagged('Reviewable result.', state='check', ask='Review it'), compacted=1, message_uid='live-logical')
        manager.scan()
        self.assertFalse(manager.summarize())
        self.assertEqual(manager.setting('ready_cursor'), good)
        self.assertEqual(manager.state()['messages'], [])
        # WAS list metadata deliberately disagrees with the actual per-response tag.
        sessions.append({'id': 'wizard_fixture', 'title': 'Fixture task', 'status': 'completed',
                         'wizard_attention': {'state': 'done', 'ask': 'Wrong session-level metadata'}})
        manager.scan(); manager.summarize(); manager.scan(); manager.summarize()
        messages = manager.state()['messages']
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]['source_message'], str(good))
        self.assertEqual(json.loads(messages[0]['attention']), {'state': 'check', 'ask': 'Review it'})
        model_calls = [body for url, body in calls if url == 'http://model']
        self.assertEqual(len(model_calls), 1)
        evidence = json.loads(model_calls[0]['messages'][-1]['content'])
        self.assertEqual(evidence['response'], 'Reviewable result.')
        self.assertNotIn('WIZARD_STATUS_V1', evidence['response'])
        # Hermes can rewrite retained history with new insertion IDs but stable UIDs.
        self.row(content=tagged('Reviewable result.', state='check', ask='Review it'), message_uid='live-logical')
        manager.scan(); manager.summarize()
        self.assertEqual(len(manager.state()['messages']), 1, 'compaction must not notify twice')

    def test_logical_identity_survives_history_reinsertion(self):
        first = self.row(message_uid='stable-logical', compacted=1)
        second = self.row(message_uid='stable-logical')
        rows, cursor, _ = self.source.read(first)
        self.assertEqual(rows[0]['id'], second)
        self.assertEqual(rows[0]['first_id'], first)
        self.assertEqual(rows[0]['identity'], 'stable-logical')
        self.assertEqual(cursor, second)

    def test_attention_rejects_invalid_metadata_and_uses_last_valid_marker(self):
        for text in ('', 'Done.', '[WIZARD_STATUS_V1][][/WIZARD_STATUS_V1]',
                     tagged(state='unrecognized'), tagged(ask='  ')):
            with self.subTest(text=text):
                self.assertIsNone(attention(text))
        value = attention(tagged(state='done') + tagged(state='needs-you', ask='  Choose\n one  '))
        self.assertEqual(value, {'state': 'needs_you', 'ask': 'Choose one'})


if __name__ == '__main__':
    unittest.main()
