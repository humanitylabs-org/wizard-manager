"""Pack exact app Python, web assets (including portrait), and API spec for Runtipi.

No registry publication or credentials. Host routes/Ready adapter remain explicit
runtime configuration; standalone installs report missing connection honestly.
"""
import base64
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
files = sorted([p for p in (ROOT / 'app').glob('*.py') if p.name != 'package.py'] +
               [p for p in (ROOT / 'web').iterdir() if p.is_file()] + [ROOT / 'openapi.json'])
payload = {str(p.relative_to(ROOT)): base64.b64encode(p.read_bytes()).decode() for p in files}
blob = base64.b64encode(json.dumps(payload, sort_keys=True).encode()).decode()
code = ("import base64,json,pathlib,runpy,sys\nroot=pathlib.Path('/tmp/wizard-app');root.mkdir(exist_ok=True)\n"
        + f"files=json.loads(base64.b64decode('{blob}'))\n"
        + "for name,value in files.items():\n p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(base64.b64decode(value))\n"
        + "sys.path.insert(0,str(root/'app'));runpy.run_path(str(root/'app/server.py'),run_name='__main__')\n")
compose = {'services': {'wizard-manager': {'image':'python:3.12-alpine','user':'1000:1000','cap_drop':['ALL'],
    'security_opt':['no-new-privileges:true'],'mem_limit':'256m','tmpfs':['/tmp'],'read_only':True,
    'environment':{'PORT':'8799','BIND':'0.0.0.0','DATA_DIR':'/data',
        **{k:'${'+k+':-}' for k in ['WIZARD_TRUSTED_HOSTS','WIZARD_TRUSTED_ORIGINS','MANAGER_WAS_URL','MANAGER_MODEL_URL','WIZARD_ROUTER_KEY','MANAGER_READY_DB']}},
    'volumes':['${APP_DATA_DIR}/data:/data'],'command':['python','-c',code],
    'x-runtipi':{'is_main':True,'internal_port':8799}}},'x-runtipi':{'schema_version':2,'overrides':[]}}
# JSON is also valid YAML and avoids a packaging dependency.
text = json.dumps(compose, indent=2) + '\n'
if '--check' in sys.argv:
    assert (ROOT/'runtipi/docker-compose.yml').read_text() == text, 'Repackage changed source'
    print('Packaged bytes match source:',len(files),'files')
else:
    (ROOT/'runtipi/docker-compose.yml').write_text(text)
    print('Packaged',len(files),'files including the portrait and domain modules')
