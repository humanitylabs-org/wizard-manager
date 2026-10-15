"""Isolated Manager regressions: no real WAS, model, or canonical user data."""
import json
import sys
import tempfile
import threading
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from manager import Manager, Problem, MODEL
from ready_source import MARKER, attention


def tagged(body='Fixture completed.', state='done', ask='Fixture completed'):
    return body + '\n[WIZARD_STATUS_V1]' + json.dumps({'state': state, 'ask': ask}) + '[/WIZARD_STATUS_V1]'


class FakeReadySource:
    """Insertion-ID reader seam; real SQL eligibility is tested separately."""
    def __init__(self, page_size=1000):
        self.rows = []
        self.page_size = page_size
        self.reads = []

    def add(self, body=None, sid='wizard_fixture', created=20):
        ident = self.head() + 1
        self.rows.append({'id': ident, 'session_id': sid, 'content': body if body is not None else tagged(),
                          'created': created})
        return ident

    def head(self):
        return max((r['id'] for r in self.rows), default=0)

    def read(self, after, limit=1000):
        self.reads.append(after)
        limit = min(limit, self.page_size)
        rows = [r for r in self.rows if r['id'] > after][:limit]
        events = []
        for row in rows:
            value = attention(row['content'])
            if value:
                events.append({'id': row['id'], 'session_id': row['session_id'],
                               'body': MARKER.sub('', row['content']).strip(),
                               'attention': value, 'created': row['created']})
        return events, rows[-1]['id'] if rows else after, len(rows) == limit


class FakeAPI:
    """Deterministic isolated fixtures, never used as production evidence."""
    def __init__(self):
        self.calls = []
        self.sessions = []
        self.output = '{"action":"reply","text":"Hello."}'
        self.fail = False
        self.was_fail = False
        self.response_model = MODEL
        self.on_create: Callable | None = None
        self.on_run: Callable | None = None
        self.receipts = {}
        self.crash_after_receipt = False

    def __call__(self, url, body=None, headers=None, method=None, timeout=30):
        self.calls.append((url, body, headers, method))
        if url == 'http://model':
            if self.fail:
                raise RuntimeError('simulated model offline')
            return {'model': self.response_model, 'choices': [{'message': {'content': self.output}}]}
        if self.was_fail:
            raise RuntimeError('simulated WAS offline')
        if '/messages?' in url:
            from urllib.parse import parse_qs, urlparse
            offset = int(parse_qs(urlparse(url).query).get('offset', ['0'])[0])
            return {'data': [], 'pagination': {'offset': offset, 'order': 'latest', 'returned': 0}}
        if '/api/sessions?' in url:
            return {'data': self.sessions, 'has_more': False, 'snapshot': 'fixture'}
        if '/api/sessions/' in url and body is None:
            sid = url.rsplit('/', 1)[-1]
            return {'session': next((s for s in self.sessions if s['id'] == sid), None)}
        if url.endswith('/api/sessions') and body is not None and self.on_create:
            self.on_create()
        if url.endswith('/v1/runs'):
            if self.on_run:
                self.on_run()
            assert headers is not None
            key = headers['Idempotency-Key']
            payload = json.dumps(body, sort_keys=True)
            if key in self.receipts:
                assert self.receipts[key][0] == payload, 'replay changed an accepted run payload'
            else:
                self.receipts[key] = (payload, {'run_id': 'fixture-run', 'status': 'queued'})
            if self.crash_after_receipt:
                self.crash_after_receipt = False
                raise SystemExit('simulated crash after WAS acceptance')
            return self.receipts[key][1]
        return {'id': (body or {}).get('id', 'fixture')}


class ManagerTests(unittest.TestCase):
    def setUp(self):
        # Never resolve an inherited live canonical store, even in opt-out tests.
        env = patch.dict('os.environ', {'MANAGER_READY_DB': ''})
        env.start()
        self.addCleanup(env.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.api = FakeAPI()
        self.source = FakeReadySource()
        self.m = self.manager()

    def manager(self, source=None):
        return Manager(self.temp.name, was='http://was', model_url='http://model', key='fixture-only',
                       request=self.api, ready_source=self.source if source is None else source)

    def send(self, text='Hello', ident='request_0001', reply_to=None):
        return self.m.submit({'text': text, 'request_id': ident, 'reply_to': reply_to})

    def ready(self):
        self.api.sessions = [{'id': 'wizard_fixture', 'title': 'Fixture task', 'wizard_last_assistant_at': 20,
            'wizard_last_run_status': 'completed', 'wizard_attention': {'state': 'done', 'ask': 'Fixture completed'}}]
        self.api.output = 'Fixture completed. Nothing needed.'
        return self.source.add()

    def event_statuses(self, manager=None):
        with (manager or self.m).connect() as c:
            return [r[0] for r in c.execute('SELECT status FROM events ORDER BY rowid')]

    def test_slow_summary_does_not_block_inventory_refresh_or_visibility_removal(self):
        self.ready()
        self.m.sessions(fresh=True)
        entered, release = threading.Event(), threading.Event()
        threads = []
        real_thread = threading.Thread

        class FastStop(threading.Event):
            def wait(self, timeout=None):
                return super().wait(min(timeout or 0.01, 0.01))

        def tracked_thread(*args, **kwargs):
            thread = real_thread(*args, **kwargs)
            threads.append(thread)
            return thread

        def slow_summary():
            entered.set()
            release.wait(3)
            return False

        def wait_for(predicate):
            deadline = time.monotonic() + 1
            while not predicate() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(predicate(), 'inventory monitor remained blocked by summary')

        self.m.stop = FastStop()
        with patch.object(self.m, 'summarize', slow_summary), patch('manager.threading.Thread', tracked_thread):
            try:
                self.m.start()
                self.assertTrue(entered.wait(1))
                self.m.cache_at = time.time() - 60
                wait_for(lambda: bool(self.m.thread_inventory()))
                self.assertEqual(self.m.thread_inventory()[0]['id'], 'wizard_fixture')
                self.assertFalse(release.is_set(), 'summary must still be blocked')
                self.api.sessions = []
                wait_for(lambda: not self.m.thread_inventory())
                self.assertLess(time.time() - self.m.cache_at, 45, 'removal came from fresh canonical inventory')
            finally:
                self.m.stop.set()
                self.m.wake.set()
                release.set()
                for thread in threads:
                    thread.join(2)
                self.m.dispatch_pool.shutdown(wait=True)
                self.assertFalse(any(thread.is_alive() for thread in threads))

    def test_thread_inventory_uses_visible_canonical_snapshot_without_history_mutation(self):
        self.api.sessions = [
            {'id': 'visible/one', 'title': 'Wizard OS · Share files'},
            {'id': 'hidden', 'title': 'Secret thread', 'hidden': True},
            {'id': 'archived', 'title': 'Old thread', 'archived': True},
            {'id': 'private', 'title': 'Private thread', 'agent': {'id': 'private'}},
            {'id': 'child', 'title': 'Child thread', 'parent_session_id': 'visible/one'}]
        self.send('Share files'); self.m.process_job()
        before = self.m.state()['messages']
        self.m.sessions(fresh=True)
        calls = len(self.api.calls)
        state = self.m.state()
        self.assertEqual(state['threads'], [{'id': 'visible/one', 'title': 'Wizard OS · Share files', 'aliases': []}])
        self.assertEqual(state['messages'], before)
        self.assertEqual(len(self.api.calls), calls, 'display projection must not call a provider')
        self.assertEqual(self.m.state(after=state['messages'][-1]['id'])['threads'], state['threads'])
        self.m.cache_at = time.time() - 46
        self.assertEqual(self.m.state()['threads'], [], 'stale inventory cannot authorize a new link')
        self.api.sessions = []
        self.m.sessions(fresh=True)
        self.assertEqual(self.m.state()['threads'], [])

    def test_observed_title_survives_rename_and_restart_but_not_visibility_removal(self):
        self.api.sessions = [{'id': 'same-id', 'title': 'Original thread title'}]
        self.m.sessions(fresh=True)
        self.api.sessions[0]['title'] = 'Renamed work'
        other = self.manager()
        other.sessions(fresh=True)
        self.assertEqual(other.state()['threads'], [{'id': 'same-id', 'title': 'Renamed work', 'aliases': ['Original thread title']}])
        self.api.sessions = [{'id': 'same-id', 'title': 'Renamed work', 'hidden': True}]
        other.sessions(fresh=True)
        self.assertEqual(other.state()['threads'], [])

    def test_model_receives_canonical_urls_and_every_named_thread_contract(self):
        self.api.sessions = [{'id': 'fixture/one', 'title': 'First work'}, {'id': 'fixture-two', 'title': 'Second work'}]
        self.m.sessions(fresh=True)
        self.send('What is happening?'); self.m.process_job()
        request = next(c[1] for c in self.api.calls if c[0] == 'http://model')
        self.assertIn('Link every named thread', request['messages'][0]['content'])
        self.assertNotIn('No markdown links', request['messages'][0]['content'])
        work = json.loads(request['messages'][1]['content'])['work']
        self.assertEqual([s['url'] for s in work], ['/wizard-os-home/?session=fixture%2Fone', '/wizard-os-home/?session=fixture-two'])

    def test_reply_persists(self):
        self.send()
        self.m.process_job()
        other = self.manager()
        self.assertEqual(other.state()['messages'][-1]['text'], 'Hello.')
        self.assertEqual(other.state()['jobs'], [])

    def test_send_idempotency(self):
        self.send(); self.send(); self.m.process_job(); self.m.process_job()
        self.assertEqual(len(self.m.state()['messages']), 2)
        self.assertEqual(self.m.model_calls, 1)

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
        self.assertFalse(self.manager().enabled())

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
        self.assertEqual(self.m.state()['messages'][-1]['kind'], 'delegation')
        calls = [c for c in self.api.calls if c[0].endswith('/v1/runs')]
        self.assertEqual(calls[0][2]['Idempotency-Key'], 'manager-request_0001')
        self.assertTrue(calls[0][1]['input'].endswith('Investigate a fixture'))
        with self.m.connect() as c:
            row = c.execute('SELECT * FROM jobs').fetchone()
            self.assertEqual(row['run_id'], 'fixture-run')
            self.assertIsNotNone(row['plan'])

    def test_alias_prompt_describes_real_handoff_not_external_products(self):
        self.send(); self.m.process_job()
        prompt = next(c[1]['messages'][0]['content'] for c in self.api.calls if c[0] == 'http://model')
        for alias in ('Archimedes', 'main agent', 'main assistant', 'GPT-Astra', 'Astra',
                      'GBT Astra', 'ChatGPT', 'GPT', 'Claude', 'Hermes'):
            self.assertIn(alias, prompt)
        self.assertIn('even for a small task or joke', prompt)
        self.assertIn('not provider switching', prompt)
        self.assertIn('Ordinary mentions or comparisons', prompt)
        self.assertIn('not thread names', prompt)
        self.assertNotIn('No tools, file access or external actions are available to you', prompt)

    def test_pass_joke_preserves_context_and_latest_request_verbatim(self):
        joke = 'What do you call a wizard who is high on the good times?'
        self.send(joke); self.m.process_job()
        self.api.output = '{"action":"delegate","title":"Wizard joke"}'
        latest = 'Please pass it on to GPT-Astra.'
        self.send(latest, ident='request_0002'); self.m.process_job()
        runs = [c for c in self.api.calls if c[0].endswith('/v1/runs')]
        self.assertEqual(len(runs), 1)
        text = runs[0][1]['input']
        self.assertIn(joke, text)
        self.assertIn('Untrusted prior conversation', text)
        self.assertIn('no renewed authority', text)
        self.assertTrue(text.endswith('Latest user request (verbatim):\n' + latest))
        with self.m.connect() as c:
            plan = json.loads(c.execute('SELECT plan FROM jobs WHERE id=?', ('request_0002',)).fetchone()[0])
        self.assertEqual(plan['request_text'], text)

    def test_context_is_cut_off_at_admitted_message_not_processing_time(self):
        self.send('Earlier topic'); self.m.process_job()
        self.send('Please ask Astra about it.', ident='request_0002')
        # Delayed assistant output and queued user requests must not leak backward.
        with self.m.connect() as c:
            c.execute("INSERT INTO messages(role,text,created) VALUES ('assistant','LATE ANSWER',0)")
        self.send('LATER PRIVATE REQUEST', ident='request_0003')
        self.api.output = '{"action":"delegate","title":"Earlier topic"}'
        self.m.process_job()
        request = [c[1] for c in self.api.calls if c[0] == 'http://model'][-1]
        content = json.loads(request['messages'][1]['content'])
        self.assertEqual(content['last_user_request'], 'Please ask Astra about it.')
        self.assertEqual([r['text'] for r in content['conversation']], ['Earlier topic', 'Hello.'])
        text = [c[1]['input'] for c in self.api.calls if c[0].endswith('/v1/runs')][-1]
        self.assertNotIn('LATE ANSWER', text)
        self.assertNotIn('LATER PRIVATE REQUEST', text)

    def test_context_is_bounded_and_excludes_unrelated_ready_summaries(self):
        with self.m.connect() as c:
            for i in range(30):
                c.execute('INSERT INTO messages(role,text,created) VALUES (?,?,?)',
                          ('user', str(i) + 'x' * 5000, 0))
            c.execute("INSERT INTO messages(role,text,created,kind,source_id) VALUES ('assistant','PRIVATE READY CONTENT',0,'ready','other')")
        self.api.output = '{"action":"delegate","title":"Bounded"}'
        self.send('Ask Hermes to summarize our recent chat.'); self.m.process_job()
        content = json.loads(next(c[1]['messages'][1]['content'] for c in self.api.calls if c[0] == 'http://model'))
        history = content['conversation']
        self.assertLessEqual(len(history), 12)
        self.assertLessEqual(sum(len(r['text']) for r in history), 12000)
        self.assertTrue(all(len(r['text']) <= 3000 for r in history))
        self.assertTrue(history[-1]['text'].startswith('29'))
        self.assertNotIn('PRIVATE READY CONTENT', json.dumps(content))
        text = next(c[1]['input'] for c in self.api.calls if c[0].endswith('/v1/runs'))
        self.assertNotIn('PRIVATE READY CONTENT', text)

    def test_explicit_reply_includes_only_selected_ready_target(self):
        self.ready(); self.m.scan(); self.m.summarize()
        target = self.m.state()['messages'][0]
        with self.m.connect() as c:
            c.execute("INSERT INTO messages(role,text,created,kind,source_id) VALUES ('assistant','UNRELATED READY',0,'ready','other')")
        self.send('Please explain this result.', reply_to=target['id']); self.m.process_job()
        text = next(c[1]['input'] for c in self.api.calls if c[0].endswith('/v1/runs'))
        self.assertIn(target['text'], text)
        self.assertNotIn('UNRELATED READY', text)
        self.assertIn('no renewed authority', text)

    def test_context_payload_is_saved_before_first_external_side_effect(self):
        self.send('Original joke'); self.m.process_job()
        self.api.output = '{"action":"delegate","title":"Joke"}'
        def check_frozen():
            with self.m.connect() as c:
                plan = json.loads(c.execute('SELECT plan FROM jobs WHERE id=?', ('request_0002',)).fetchone()[0])
            self.assertIn('Original joke', plan['request_text'])
            self.send('ADMITTED DURING DISPATCH', ident='request_0003')
        self.api.on_create = check_frozen
        self.send('Please pass it on to Astra.', ident='request_0002'); self.m.process_job()
        self.assertEqual(self.m.state()['jobs'][0]['id'], 'request_0003')
        text = next(c[1]['input'] for c in self.api.calls if c[0].endswith('/v1/runs'))
        self.assertNotIn('ADMITTED DURING DISPATCH', text)

    def test_context_survives_crash_and_later_messages_without_payload_change(self):
        self.send('What do you call a wizard who is high on the good times?'); self.m.process_job()
        self.api.output = '{"action":"delegate","title":"Wizard joke"}'
        self.api.crash_after_receipt = True
        self.send('Please pass it on to GPT-Astra.', ident='request_0002')
        with self.assertRaises(SystemExit):
            self.m.process_job()
        self.send('LATER PRIVATE TOPIC', ident='request_0003')
        other = self.manager()
        other.process_job()
        self.assertEqual(other.model_calls, 0)
        runs = [c for c in self.api.calls if c[0].endswith('/v1/runs')]
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[0][1:3], runs[1][1:3])
        self.assertIn('high on the good times?', runs[1][1]['input'])
        self.assertNotIn('LATER PRIVATE TOPIC', runs[1][1]['input'])
        self.assertEqual(len(self.api.receipts), 1)

    def test_legacy_persisted_plan_replays_original_payload_without_context(self):
        self.send('Earlier private chat'); self.m.process_job()
        self.send('Legacy request', ident='request_0002')
        legacy = {'action': 'delegate', 'title': 'Existing plan'}
        # A deployment may interrupt an already accepted pre-context dispatch.
        expected = ("[Relayed by Archimedes Manager at the user's request. This is an explicit user instruction, "
                    "forwarded verbatim below. Finish the task in this thread; ordinary authorization boundaries still apply.]\n\nLegacy request")
        with self.m.connect() as c:
            c.execute("UPDATE jobs SET plan=?,status='working' WHERE id=?", (json.dumps(legacy), 'request_0002'))
        other = self.manager(); other.process_job()
        self.assertEqual(other.model_calls, 0)
        run = next(c[1] for c in self.api.calls if c[0].endswith('/v1/runs'))
        self.assertEqual(run['input'], expected)
        with other.connect() as c:
            plan = json.loads(c.execute('SELECT plan FROM jobs WHERE id=?', ('request_0002',)).fetchone()[0])
        self.assertEqual(plan['request_text'], expected)

    def test_model_cannot_supply_or_rewrite_forwarded_request(self):
        self.api.output = json.dumps({'action': 'delegate', 'title': 'Exact request',
                                      'request_text': 'MODEL-INVENTED INSTRUCTION'})
        latest = 'Ask Astra to read this exactly:\n\n"Keep  two spaces."\n' + 'z' * 11000
        self.send(latest); self.m.process_job()
        text = next(c[1]['input'] for c in self.api.calls if c[0].endswith('/v1/runs'))
        self.assertTrue(text.endswith('Latest user request (verbatim):\n' + latest))
        self.assertNotIn('MODEL-INVENTED INSTRUCTION', text)

    def test_missing_admitted_message_fails_closed_without_dispatch(self):
        self.send('Ask Astra to act.')
        with self.m.connect() as c:
            c.execute('DELETE FROM messages')
        self.m.process_job()
        self.assertEqual(self.m.state()['jobs'][0]['status'], 'failed')
        self.assertEqual(self.api.calls, [])

    def test_ready_once_across_restart(self):
        ident = self.ready(); self.m.scan(); self.m.summarize(); self.m.scan()
        m2 = self.manager()
        m2.scan(); m2.summarize()
        self.assertEqual(len(m2.state()['messages']), 1)
        self.assertEqual(m2.state()['messages'][0]['source_message'], str(ident))
        self.assertEqual(m2.model_calls, 0)
        self.assertEqual(self.event_statuses(m2), ['done'])

    def test_backlog_multiple_responses_preserved(self):
        self.ready()
        self.source.add(tagged('Earlier fixture final.', state='check', ask='Check it'), created=10)
        self.source.add('Historical helper handoff, no per-response Ready tag.', created=20)
        self.m.scan(); self.m.summarize(); self.m.summarize(); self.m.summarize()
        messages = self.m.state()['messages']
        self.assertEqual({m['source_message'] for m in messages}, {'1', '2'})
        self.assertEqual({json.loads(m['attention'])['state'] for m in messages}, {'done', 'check'})

    def test_active_states_hold_then_release_the_same_event(self):
        self.ready()
        for field in ('status', 'wizard_last_run_status'):
            for state in ('accepted', 'queued', 'running', 'waiting_for_approval', 'stopping'):
                with self.subTest(field=field, state=state):
                    self.api.sessions[0]['status'] = 'idle'
                    self.api.sessions[0]['wizard_last_run_status'] = 'completed'
                    self.api.sessions[0][field] = state
                    self.m.scan()
                    self.assertEqual(self.event_statuses(), ['held'])
                    self.assertFalse(self.m.summarize())
                    self.assertEqual(self.m.model_calls, 0)
        self.api.sessions[0]['status'] = 'idle'
        self.api.sessions[0]['wizard_last_run_status'] = 'completed'
        self.api.sessions[0]['wizard_waiting_on'] = 'approval'
        self.m.scan()
        self.assertEqual(self.event_statuses(), ['held'])
        self.api.sessions[0]['wizard_waiting_on'] = None
        self.m.scan(); self.m.summarize()
        self.assertEqual(self.event_statuses(), ['done'])
        self.assertEqual(len(self.m.state()['messages']), 1)

    def test_private_hidden_archived_and_child_sessions_do_not_deliver(self):
        self.ready()
        original = dict(self.api.sessions[0])
        for field, value in [('agent', {'id': 'private'}), ('hidden', True), ('archived', True),
                             ('parent_session_id', 'parent')]:
            with self.subTest(field=field):
                self.api.sessions = [{**original, field: value}]
                self.m.scan()
                self.assertEqual(self.event_statuses(), ['held'])
                self.assertFalse(self.m.summarize())
                self.assertEqual(self.m.state()['messages'], [])
        self.assertEqual(self.m.model_calls, 0)

    def test_not_yet_was_visible_event_survives_cursor_restart_and_delivers(self):
        ident = self.ready()
        visible = self.api.sessions
        self.api.sessions = []
        self.m.scan()
        self.assertEqual(self.m.setting('ready_cursor'), ident)
        self.assertEqual(self.event_statuses(), ['held'])
        self.assertFalse(self.m.summarize())
        other = self.manager()
        other.scan()
        self.assertEqual(self.event_statuses(other), ['held'])
        self.api.sessions = visible
        other.scan(); other.summarize(); other.scan(); other.summarize()
        self.assertEqual([m['source_message'] for m in other.state()['messages']], [str(ident)])
        self.assertEqual(other.state()['messages'][0]['title'], visible[0]['title'])
        self.assertEqual(self.event_statuses(other), ['done'])

    def test_initial_cursor_excludes_pre_opt_in_history(self):
        old = self.ready()
        with tempfile.TemporaryDirectory() as path:
            other = Manager(path, was='http://was', model_url='http://model', key='fixture-only',
                            request=self.api, ready_source=self.source)
            self.assertEqual(other.setting('ready_cursor'), old)
            new = self.source.add(tagged('New result.'))
            other.scan(); other.summarize()
            self.assertEqual([m['source_message'] for m in other.state()['messages']], [str(new)])

    def test_pagination_catch_up_and_clock_regression_keep_every_new_event(self):
        self.source.page_size = 2
        self.ready()
        self.source.add('No tag here', created=20)
        self.source.add(tagged('Second result.'), created=20)
        self.source.add(tagged('Clock regressed.'), created=1)
        self.source.add(tagged('Final page.'), created=0)
        self.assertTrue(self.m.scan())
        self.assertEqual(self.m.setting('ready_cursor'), 2)
        self.assertTrue(self.m.scan())
        self.assertFalse(self.m.scan())
        for _ in range(6):
            self.m.summarize()
        self.assertEqual({m['source_message'] for m in self.m.state()['messages']}, {'1', '3', '4', '5'})
        self.assertEqual(self.source.reads, [0, 2, 4])
        other = self.manager()
        other.scan(); other.summarize()
        self.assertEqual(len(other.state()['messages']), 4)
        self.assertEqual(other.setting('ready_cursor'), 5)

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
        self.api.fail = False
        other = self.manager()
        with other.connect() as c:
            c.execute('UPDATE events SET retry_at=0')
        other.summarize(); other.summarize()
        self.assertEqual(len(other.state()['messages']), 1)

    def test_restart_recovers_interrupted_jobs(self):
        self.send()
        with self.m.connect() as c:
            c.execute("UPDATE jobs SET status='working'")
        m2 = self.manager()
        m2.process_job()
        self.assertEqual(m2.state()['messages'][-1]['text'], 'Hello.')

    def test_plain_chat_answers_during_was_outage_without_inventory_read(self):
        self.api.was_fail = True
        self.send(); self.m.process_job()
        self.assertEqual(self.m.state()['messages'][-1]['text'], 'Hello.')
        self.assertEqual(self.m.state()['jobs'], [])
        self.assertEqual([c[0] for c in self.api.calls], ['http://model'])
        context = json.loads(self.api.calls[0][1]['messages'][-1]['content'])
        self.assertFalse(context['work_status_current'])
        self.assertEqual(context['work'], [])

    def test_cached_inventory_cannot_authorize_status_after_lookup_failure(self):
        self.ready()
        self.m.sessions(fresh=True)
        self.api.calls.clear()
        self.api.was_fail = True
        self.api.output = '{"action":"reply","text":"Current work lookup is unavailable."}'
        self.send('What is the fixture status?'); self.m.process_job()
        self.assertIsNone(self.m.state()['messages'][-1]['source_id'])
        context = json.loads(next(c[1] for c in self.api.calls if c[0] == 'http://model')['messages'][-1]['content'])
        self.assertFalse(context['work_status_current'])
        self.assertEqual(context['work'], [])
        self.assertEqual(context['lookup']['state'], 'unavailable')

    def test_stale_inventory_is_labelled_not_refreshed_in_foreground(self):
        self.ready(); self.m.sessions(fresh=True)
        self.m.cache_at = time.time() - 60
        self.api.calls.clear()
        self.api.was_fail = True
        self.api.output = '{"action":"reply","text":"Current work status is unavailable."}'
        self.send('Status?'); self.m.process_job()
        self.assertEqual([c[0] for c in self.api.calls], ['http://model'])
        context = json.loads(self.api.calls[0][1]['messages'][-1]['content'])
        self.assertFalse(context['work_status_current'])

    def test_foreground_submit_and_pause_stay_fast_while_run_request_blocks(self):
        entered, release, submitted = threading.Event(), threading.Event(), threading.Event()
        failures = []
        def block():
            entered.set()
            if not release.wait(5):
                raise RuntimeError('test did not release the run request')
        self.api.on_run = block
        self.api.output = '{"action":"delegate","title":"Fixture task"}'
        self.send('Investigate a fixture')
        worker = threading.Thread(target=self.m.process_job, daemon=True)
        worker.start()
        submitter = None
        try:
            self.assertTrue(entered.wait(2), 'dispatch did not reach the network barrier')
            def submit_and_pause():
                try:
                    self.send('Hello again', ident='request_0002')
                    self.m.configure({'enabled': False})
                except BaseException as exc:
                    failures.append(exc)
                finally:
                    submitted.set()
            submitter = threading.Thread(target=submit_and_pause, daemon=True)
            submitter.start()
            self.assertTrue(submitted.wait(1), 'foreground admission/pause blocked behind /v1/runs')
            self.assertEqual(failures, [])
            self.assertFalse(self.m.enabled())
            self.assertFalse(release.is_set())
            self.assertEqual([j['id'] for j in self.m.state()['jobs'] if j['status'] == 'queued'], ['request_0002'])
        finally:
            release.set()
            worker.join(3)
            if submitter:
                submitter.join(3)
        self.assertFalse(worker.is_alive())
        if submitter:
            self.assertFalse(submitter.is_alive())

    def test_dispatch_pool_keeps_chat_answers_flowing_while_runs_are_blocked(self):
        from concurrent.futures import ThreadPoolExecutor
        entered, release = threading.Event(), threading.Event()
        def block():
            entered.set()
            if not release.wait(5):
                raise RuntimeError('test did not release the run request')
        self.api.on_run = block
        self.api.output = '{"action":"delegate","title":"Fixture task"}'
        # Exercise the same pool seam as start(), without launching an unjoined watcher.
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.m.dispatch_pool = pool
            try:
                self.send('Investigate a fixture'); self.m.process_job()
                self.assertTrue(entered.wait(2))
                self.api.output = '{"action":"reply","text":"Hello while work dispatches."}'
                self.send('Hello again', ident='request_0002'); self.m.process_job()
                self.assertFalse(release.is_set())
                self.assertEqual(self.m.state()['messages'][-1]['text'], 'Hello while work dispatches.')
                self.assertEqual([j['id'] for j in self.m.state()['jobs']], ['request_0001'])
            finally:
                release.set()
        self.assertEqual(self.m.state()['jobs'], [])

    def test_existing_target_is_revalidated_not_authorized_by_stale_cache(self):
        self.ready(); self.m.sessions(fresh=True)
        self.api.sessions = []
        self.api.output = '{"action":"delegate","session_id":"wizard_fixture"}'
        self.send('Continue the fixture'); self.m.process_job()
        self.assertEqual(self.m.state()['jobs'][0]['status'], 'failed')
        self.assertFalse(any(c[0].endswith('/v1/runs') for c in self.api.calls))

    def test_pause_after_creation_prevents_title_patch_and_run_until_resumed(self):
        self.api.on_create = lambda: self.m.configure({'enabled': False})
        self.api.output = '{"action":"delegate","title":"Frozen fixture title"}'
        self.send('Investigate a fixture'); self.m.process_job()
        self.assertFalse(any(c[3] == 'PATCH' or c[0].endswith('/v1/runs') for c in self.api.calls))
        self.assertEqual(self.m.state()['jobs'][0]['status'], 'queued')
        with self.m.connect() as c:
            frozen = c.execute('SELECT plan FROM jobs').fetchone()[0]
        self.api.on_create = None
        self.api.output = '{"action":"reply","text":"This changed decision must not run."}'
        self.m.configure({'enabled': True}); self.m.process_job()
        self.assertEqual(self.m.model_calls, 1)
        self.assertEqual(self.m.state()['messages'][-1]['kind'], 'delegation')
        self.assertEqual([c[1]['title'] for c in self.api.calls if c[3] == 'PATCH'], ['Frozen fixture title'])
        with self.m.connect() as c:
            self.assertEqual(c.execute('SELECT plan FROM jobs').fetchone()[0], frozen)

    def test_crash_after_acceptance_replays_identical_plan_key_and_run_payload(self):
        self.api.output = '{"action":"delegate","title":"Stable title"}'
        self.api.crash_after_receipt = True
        self.send('Investigate a fixture')
        with self.assertRaises(SystemExit):
            self.m.process_job()
        self.assertEqual(len(self.api.receipts), 1)
        self.assertEqual(len(self.m.state()['messages']), 1)
        self.api.output = '{"action":"reply","text":"Different model decision"}'
        other = self.manager()
        other.process_job(); other.process_job()
        self.assertEqual(other.model_calls, 0)
        runs = [c for c in self.api.calls if c[0].endswith('/v1/runs')]
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[0][1:3], runs[1][1:3])
        self.assertEqual(len(self.api.receipts), 1)
        self.assertEqual(len(other.state()['messages']), 2)
        self.assertEqual(other.state()['jobs'], [])
        last = self.manager()
        last.process_job()
        self.assertEqual(len(last.state()['messages']), 2)
        self.assertEqual(len([c for c in self.api.calls if c[0].endswith('/v1/runs')]), 2)

    def test_ready_is_opt_in_chat_remains_available(self):
        with tempfile.TemporaryDirectory() as path:
            other = Manager(path, was='http://was', model_url='http://model', key='fixture-only', request=self.api)
            self.assertIsNone(other.ready_source)
            other.scan()
            self.assertIn('not configured', other.state()['monitor']['error'])
            other.submit({'text': 'Hello', 'request_id': 'request_0001'})
            other.process_job()
            self.assertEqual(other.state()['messages'][-1]['text'], 'Hello.')


if __name__ == '__main__':
    unittest.main()
