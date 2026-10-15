"""Explicit live read-only QA follow-up using real WAS + DeepSeek + Ready source."""
import argparse
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from manager import Manager
p=argparse.ArgumentParser();p.add_argument('--data',required=True);p.add_argument('--out',required=True);a=p.parse_args()
m=Manager(a.data);m.sessions(fresh=True)
ready=next(x for x in reversed(m.state()['messages']) if x['kind']=='ready' and x['source_id'].startswith('wizard_manager_'))
sid=ready['source_id']
with m.connect() as c:
    before=c.execute("SELECT count(*) FROM messages WHERE kind='ready' AND source_id=?",(sid,)).fetchone()[0]
request_id='manager_acceptance_followup_v2'
m.submit({'request_id':request_id,'reply_to':ready['id'],'text':'This is a follow-up technical acceptance test, not James speaking. Reply in one sentence repeating the Python executable path you previously verified; no new commands or changes. Mark the result done with no action needed.'})
m.process_job()
with m.connect() as c: job=dict(c.execute('SELECT * FROM jobs WHERE id=?',(request_id,)).fetchone())
assert job['status']=='done',job
run={}
for _ in range(40):
    run=m.request(m.was+'/v1/runs/'+job['run_id'])
    if run.get('status') in ('completed','failed','cancelled'):break
    time.sleep(2)
assert run.get('status')=='completed',run
for _ in range(5):
    m.scan()
    for _ in range(20):
        if not m.summarize():break
    with m.connect() as c: after=c.execute("SELECT count(*) FROM messages WHERE kind='ready' AND source_id=?",(sid,)).fetchone()[0]
    if after>before:break
    time.sleep(2)
assert after==before+1,(before,after)
m2=Manager(a.data);m2.scan()
for _ in range(20):
    if not m2.summarize():break
with m2.connect() as c: repeated=c.execute("SELECT count(*) FROM messages WHERE kind='ready' AND source_id=?",(sid,)).fetchone()[0]
assert repeated==after,(repeated,after)
result={'session_id':sid,'run_id':job['run_id'],'run_status':run['status'],'worker_output':run.get('output'),'new_ready_count':after-before,'after_restart_count':repeated,'ready_source':'read-only retained per-response evidence','summary':next(x for x in reversed(m2.state()['messages']) if x['kind']=='ready' and x['source_id']==sid)}
Path(a.out).write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
