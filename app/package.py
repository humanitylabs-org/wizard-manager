"""Generate the portable source-package recipe; no registry or embedded app payload.

Host routes/Ready adapter remain explicit runtime configuration; standalone
installs report missing connections honestly.
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
compose = {'services': {'wizard-manager': {
    'image': 'python:3.12-alpine@sha256:1b668429b3511ab407d8e00648891631b0b1a4d7e15e3ca70f38ab5b91ad4ab4',
    # App Manager creates root-owned binds. No ownership-preparing custom image.
    'user': '0:0', 'working_dir': '/app',
    'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true'],
    'mem_limit': '256m', 'tmpfs': ['/tmp'], 'read_only': True,
    'environment': {'PORT': '8799', 'BIND': '0.0.0.0', 'DATA_DIR': '/data',
        'PYTHONDONTWRITEBYTECODE': '1',
        **{k: '${' + k + ':-}' for k in ['WIZARD_TRUSTED_HOSTS', 'WIZARD_TRUSTED_ORIGINS',
            'MANAGER_WAS_URL', 'MANAGER_MODEL_URL', 'WIZARD_ROUTER_KEY', 'MANAGER_READY_DB']}},
    'volumes': ['${APP_SOURCE_DIR}:/app:ro', '${APP_DATA_DIR}/data:/data'],
    'command': ['python', '/app/app/server.py'],
    'x-runtipi': {'is_main': True, 'internal_port': 8799}
}}, 'x-runtipi': {'schema_version': 2, 'overrides': []}}
# JSON is also valid YAML and avoids a packaging dependency.
text = json.dumps(compose, indent=2) + '\n'
if '--check' in sys.argv:
    assert (ROOT / 'runtipi/docker-compose.yml').read_text() == text, 'Regenerate runtime recipe'
    print('Source-package recipe matches')
else:
    (ROOT / 'runtipi/docker-compose.yml').write_text(text)
    print('Source-package recipe generated')
