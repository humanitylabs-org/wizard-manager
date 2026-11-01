"""Opt-in real-route acceptance. Hidden workers, separate app DB and prefs.

The QA adapter projects ONLY its own hidden worker metadata as visible to this
isolated app instance. Ready input is a verbatim copy of canonical final rows
for those exact ids into a disposable SQLite source, never invented text.
Canonical session.hidden is verified before every first run and never cleared.
No owner Space, message, source read-state or production Manager DB is changed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from urllib.parse import urlsplit

p = argparse.ArgumentParser()
p.add_argument('--out', required=True)
p.add_argument('--phase', choices=['dispatch', 'followup'], required=True)
a = p.parse_args()
out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
# Use the existing runtime environment, without printing or copying credentials.
env = Path.home() / '.config/wizard-manager/runtime.env'
for line in env.read_text().splitlines():
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1); os.environ.setdefault(k, v.strip('"\''))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from manager import http_json, MODEL
from projects import ProjectManager
from ready_source import ReadySource

was = os.environ['MANAGER_WAS_URL']
canonical = Path(os.environ['MANAGER_READY_DB'])
qa_id = 'project_chats_qa_dispatch_20261101'
sid = 'wizard_manager_' + hashlib.sha256(qa_id.encode()).hexdigest()[:24]
ids = {sid}
prefs = out / 'qa-preferences.json'
prefs.write_text(json.dumps({'spaces':[{'id':'project-chats-qa','name':'Project Chats QA (isolated)','threads':[]}]}))
source = out / 'authentic-ready-source.sqlite3'
with sqlite3.connect(source) as c:
    c.executescript('''CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,hidden INTEGER,parent_session_id TEXT,archived INTEGER);
    CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,message_uid TEXT,session_id TEXT,role TEXT,content TEXT,timestamp REAL,finish_reason TEXT,display_kind TEXT,tool_calls TEXT);''')


def qa_request(url, body=None, headers=None, method=None, timeout=30):
    if '/api/sessions?' in url:
        rows = []
        for ident in ids:
            try:
                session = http_json(was + '/api/sessions/' + ident, timeout=4).get('session')
                if session:
                    session = {k:v for k,v in session.items() if k != 'latest_message'}
                    assert session.get('hidden') is True, 'QA worker must stay hidden'
                    rows.append({**session, 'hidden':False})
            except Exception as e:
                if getattr(e, 'code', None) != 404: raise
        return {'data':rows,'has_more':False,'snapshot':'exact-hidden-qa-scope'}
    if url == was + '/api/sessions' and body:
        assert body.get('id') in ids
        result = http_json(url, {**body,'hidden':True,'title':'Project Chats QA (internal)'}, headers, method, timeout)
        http_json(was + '/api/sessions/' + body['id'], {'hidden':True}, method='PATCH')
        assert http_json(was + '/api/sessions/' + body['id'])['session']['hidden'] is True
        return result
    if url.startswith(was + '/api/sessions/') and body is None and '/messages' not in url:
        result = http_json(url, body, headers, method, timeout)
        if url.rsplit('/',1)[-1] in ids and result.get('session'):
            assert result['session'].get('hidden') is True
            result['session'] = {**result['session'], 'hidden':False}
        return result
    if url == was + '/v1/runs':
        assert body['session_id'] in ids
        assert http_json(was + '/api/sessions/' + body['session_id'])['session']['hidden'] is True
    return http_json(url, body, headers, method, timeout)


class QAProject(ProjectManager):
    def file_workers(self):
        # QA Space is local to the disposable app, not an owner preference write.
        pass


def open_app():
    return QAProject(out / 'app-data', request=qa_request, ready_source=ReadySource(source), prefs_path=prefs)


def run(m, request_id, text, reply_to=None):
    t = time.monotonic()
    m.submit({'request_id':request_id,'text':text,'project_id':'project-chats-qa','reply_to':reply_to})
    m.process_job()
    with m.connect() as c:
        job = dict(c.execute('SELECT * FROM jobs WHERE id=?',(request_id,)).fetchone())
    job['seconds'] = round(time.monotonic()-t,3)
    assert job['status'] == 'done', job.get('error')
    return {k:job[k] for k in ['id','status','session_id','run_id','seconds']}


m = open_app(); m.sessions(fresh=True)
result_path = out / 'real-acceptance.json'
result = json.loads(result_path.read_text()) if result_path.exists() else {'model':MODEL,'qa_scope':'separate app DB and Space; exact hidden worker metadata projection; authentic canonical final rows'}
if a.phase == 'dispatch':
    result['greeting'] = run(m, 'project_chats_qa_greeting_20261101', 'Internal technical acceptance test, not James speaking: briefly explain what Project Chats does. Answer directly; do not delegate.')
    result['dispatch'] = run(m, qa_id, 'Internal technical acceptance test, not James speaking: start a new thread for a bounded read-only verification. Use the terminal tool to print the Python executable path. Return one sentence with the verified result. Do not change files or settings, contact anyone, or start any other work. End with a WIZARD_STATUS_V1 JSON marker state done, ask Nothing needed, title Project Chats QA. This test is internal.')
    result['session_hidden'] = http_json(was+'/api/sessions/'+sid)['session']['hidden']
    result['messages'] = m.state(project_id='project-chats-qa')['messages']
else:
    # Read only this test worker's authentic final assistant rows, never a whole
    # user transcript, tools, recordings or another agent's database.
    c = sqlite3.connect(canonical.as_uri()+'?mode=ro',uri=True); c.row_factory=sqlite3.Row
    rows = [dict(r) for r in c.execute("SELECT id,message_uid,session_id,role,content,timestamp,finish_reason,display_kind,tool_calls FROM messages WHERE session_id=? AND role='assistant' AND (display_kind IS NULL OR display_kind IN ('','final')) AND (tool_calls IS NULL OR tool_calls IN ('','[]','null')) ORDER BY id",(sid,))]; c.close()
    assert any('[WIZARD_STATUS_V1]' in (r['content'] or '') for r in rows), 'Worker has not produced its Ready response yet; rerun followup later.'
    (out/'authentic-worker-final-rows.json').write_text(json.dumps(rows,indent=2))
    with sqlite3.connect(source) as c:
        c.execute('INSERT OR REPLACE INTO sessions VALUES (?,0,NULL,0)',(sid,))
        for r in rows:
            c.execute('INSERT OR IGNORE INTO messages VALUES (?,?,?,?,?,?,?,?,?)', tuple(r.values()))
    m.sessions(fresh=True); m.scan(); m.summarize()
    state = m.state(project_id='project-chats-qa')
    updates = [x for x in state['messages'] if x['kind']=='ready']
    assert len(updates)==1, 'Expected exactly one real worker update'
    result['update'] = updates[0]
    result['unread_before_restart'] = next(x for x in state['projects'] if x['id']=='project-chats-qa')['unread']
    assert result['unread_before_restart']==1
    restarted = open_app(); restarted.sessions(fresh=True); restarted.scan(); restarted.summarize()
    state = restarted.state(project_id='project-chats-qa')
    result['updates_after_restart'] = len([x for x in state['messages'] if x['kind']=='ready'])
    result['unread_after_restart'] = next(x for x in state['projects'] if x['id']=='project-chats-qa')['unread']
    assert result['updates_after_restart']==1 and result['unread_after_restart']==1
    result['followup'] = run(restarted,'project_chats_qa_followup_20261101','Internal acceptance follow-up: in one sentence explain what that Python executable path means. Read-only; do not do more work.', reply_to=updates[0]['id'])
    assert result['followup']['session_id'] == sid
    result['messages'] = restarted.state(project_id='project-chats-qa')['messages']
    result['session_hidden'] = http_json(was+'/api/sessions/'+sid)['session']['hidden']
    assert result['session_hidden'] is True
result_path.write_text(json.dumps(result,indent=2))
print(json.dumps({k:v for k,v in result.items() if k not in ['messages','update']},indent=2))
