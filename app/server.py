"""Manager HTTP/API/MCP adapter. Gateway authentication, loopback app listener."""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from manager import Manager, Problem

ROOT = Path(__file__).resolve().parent.parent
APP_ID = 'wizard-manager'
PORT = int(os.environ.get('PORT', '8799'))
DATA = Path(os.environ.get('DATA_DIR', ROOT / '.data'))
manager = None
TYPES = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.webp': 'image/webp'}
LOOPBACK = {f'127.0.0.1:{PORT}', f'localhost:{PORT}'}
TRUSTED_HOSTS = LOOPBACK | {s.strip().lower() for s in os.environ.get('WIZARD_TRUSTED_HOSTS', '').split(',') if s.strip()}
TRUSTED_ORIGINS = {'http://' + x for x in LOOPBACK} | {s.strip().lower() for s in os.environ.get('WIZARD_TRUSTED_ORIGINS', '').split(',') if s.strip()}
TOOLS = [
    {'name': 'manager_status', 'description': 'Read the optional Manager state and conversation.', 'inputSchema': {'type': 'object', 'properties': {}}},
    {'name': 'manager_message', 'description': 'Send an explicit owner request to Manager. May delegate work to a normal thread. Never use for autonomous notifications or approval inference.', 'inputSchema': {'type': 'object', 'properties': {'text': {'type': 'string'}, 'request_id': {'type': 'string'}, 'reply_to': {'type': 'integer'}}, 'required': ['text', 'request_id']}},
    {'name': 'manager_enabled', 'description': 'Enable or pause the optional Manager at the owner request.', 'inputSchema': {'type': 'object', 'properties': {'enabled': {'type': 'boolean'}}, 'required': ['enabled']}}
]


def rpc(msg):
    if not isinstance(msg, dict):
        raise Problem(400, 'Expected JSON-RPC object.')
    if 'id' not in msg:
        return None
    method, params = msg.get('method'), msg.get('params') or {}
    if method == 'initialize':
        result = {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}}, 'serverInfo': {'name': APP_ID, 'version': '0.1.0'}}
    elif method == 'tools/list':
        result = {'tools': TOOLS}
    elif method == 'ping':
        result = {}
    elif method == 'tools/call':
        name, args = params.get('name'), params.get('arguments') or {}
        if name == 'manager_status':
            value = manager.state()
        elif name == 'manager_message':
            value = manager.submit(args)
        elif name == 'manager_enabled':
            value = manager.configure(args)
        else:
            raise Problem(400, 'Unknown tool.')
        result = {'content': [{'type': 'text', 'text': json.dumps(value)}], 'structuredContent': value, 'isError': False}
    else:
        return {'jsonrpc': '2.0', 'id': msg['id'], 'error': {'code': -32601, 'message': 'Unknown method.'}}
    return {'jsonrpc': '2.0', 'id': msg['id'], 'result': result}


class Handler(BaseHTTPRequestHandler):
    def refused(self, write=False):
        if (self.headers.get('Host') or '').lower() not in TRUSTED_HOSTS:
            self.send(403, {'error': 'Unknown host.'})
            return True
        origin = (self.headers.get('Origin') or '').lower()
        if write and ((origin and origin not in TRUSTED_ORIGINS) or self.headers.get('Sec-Fetch-Site') == 'cross-site'):
            self.send(403, {'error': 'Cross-origin writes refused.'})
            return True
        return False

    def send(self, code, body=None, mime='application/json'):
        payload = body if isinstance(body, bytes) else b'' if body is None else json.dumps(body).encode()
        self.send_response(code)
        for key, val in {'Content-Type': mime, 'Content-Length': str(len(payload)), 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'self'; img-src 'self' data:"}.items():
            self.send_header(key, val)
        self.end_headers()
        if self.command != 'HEAD':
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def do_GET(self):
        if self.refused():
            return
        path = urlsplit(self.path).path
        try:
            if path == '/healthz':
                return self.send(200, {'ok': True, 'app': APP_ID, 'version': '0.1.0', 'enabled': manager.enabled()})
            if path == '/api/state':
                after = max(0, int(parse_qs(urlsplit(self.path).query).get('after', ['0'])[0]))
                return self.send(200, manager.state(after))
            if path == '/openapi.json':
                return self.send(200, (ROOT / 'openapi.json').read_bytes())
            name = 'index.html' if path == '/' else path[1:]
            kind = TYPES.get(Path(name).suffix)
            if kind and '/' not in name and not name.startswith('.') and (ROOT / 'web' / name).is_file():
                return self.send(200, (ROOT / 'web' / name).read_bytes(), kind)
            return self.send(404, {'error': 'Not found.'})
        except (ValueError, TypeError):
            return self.send(400, {'error': 'Invalid query.'})

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        if self.refused(write=True):
            return
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.send(415, {'error': 'Use application/json.'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 65536:
                return self.send(413, {'error': 'Request too large.'})
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise Problem(400, 'Expected an object.')
            path = urlsplit(self.path).path
            if path == '/api/messages':
                return self.send(202, manager.submit(body))
            if path == '/api/settings':
                return self.send(200, manager.configure(body))
            if path == '/api/retry':
                return self.send(202, manager.retry(body))
            if path == '/mcp':
                result = rpc(body)
                return self.send(202 if result is None else 200, result)
            return self.send(404, {'error': 'Not found.'})
        except Problem as e:
            return self.send(e.code, {'error': e.message})
        except (ValueError, TypeError):
            return self.send(400, {'error': 'Invalid request.'})

    def log_message(self, *args):
        pass

# ---- wizard.app-switches/1 ------------------------------------------------------------------------------------------
# Owner feature switches for the Tracker's Try it (wizard-os docs/APP_SWITCHES.md). Shared block: the same text ships in
# every Wizard app (template: wizard-app-manager templates/hello-wizard). Every new feature ships behind a switch, off by
# default: append it to SWITCHES with the issue it delivers, e.g.
#   {'id': 'compact-header', 'name': 'Compact top bar', 'description': '...', 'default': False,
#    'issues': ['humanitylabs-org/<repo>#20']}
# and gate the feature on switch_on('compact-header'). State lives on the box (DATA_DIR/switches.json), so the app's
# page, the Tracker (through the App Manager) and the agent see one state. GET/POST /api/switches, owner only: the
# box's Tailscale Serve owner login with X-Wizard-Switch: 1; never a bearer, agent grant or box-local host.
import json as _sw_json
import os as _sw_os
import re as _sw_re
import threading as _sw_threading
from pathlib import Path as _SwPath
from urllib.parse import urlsplit as _sw_urlsplit

SWITCHES = []
_SW_CONTRACT = 'wizard.app-switches/1'
_SW_ROUTE = _sw_re.compile(r'(?:/[a-z0-9][a-z0-9-]{0,62})?/api/switches/?')
_SW_LOCAL = {'localhost', '127.0.0.1', '::1', '[::1]', '0.0.0.0'}
_sw_lock = _sw_threading.Lock()


def _sw_file():
    return _SwPath(_sw_os.environ.get('WIZARD_SWITCHES_DIR') or _sw_os.environ.get('DATA_DIR') or '/data') / 'switches.json'


def _sw_saved():
    try:
        saved = _sw_json.loads(_sw_file().read_text())
    except (OSError, ValueError):
        return {}
    return saved if isinstance(saved, dict) else {}


def switches_doc():
    saved = _sw_saved()
    return {'contract': _SW_CONTRACT, 'switches': [
        dict(s, on=saved[s['id']] if isinstance(saved.get(s['id']), bool) else bool(s.get('default'))) for s in SWITCHES]}


def switch_on(switch_id):
    return next((s['on'] for s in switches_doc()['switches'] if s['id'] == switch_id), False)


def _sw_set(switch_id, on):
    with _sw_lock:
        ids = {s['id'] for s in SWITCHES}
        saved = {k: v for k, v in _sw_saved().items() if k in ids and isinstance(v, bool)}
        saved[switch_id] = on
        f = _sw_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f.name + '.tmp')
        tmp.write_text(_sw_json.dumps(saved))
        _sw_os.replace(tmp, f)
    return switches_doc()


def _sw_owner(h, write):
    hd = h.headers
    if hd.get('Authorization') or hd.get('X-Wizard-Switch') != '1':
        return False
    if (hd.get('Sec-Fetch-Site') or 'same-origin').lower() not in ('same-origin', 'none'):
        return False
    host = (hd.get('Host') or '').strip().lower()
    name = host.split(']')[0] + ']' if host.startswith('[') else host.rsplit(':', 1)[0]
    if not name or name in _SW_LOCAL or '.' not in name:      # box-local and container hosts never prove the owner
        return False
    origin = hd.get('Origin')
    trusted = {o.strip() for o in (_sw_os.environ.get('WIZARD_TRUSTED_ORIGINS') or '').split(',') if o.strip()}
    if origin and _sw_urlsplit(origin).netloc.lower() != host and origin not in trusted:
        return False
    if write and not origin:
        return False
    logins = [x.strip() for x in (hd.get_all('Tailscale-User-Login') or [])]
    owners = {x.strip().lower() for x in (_sw_os.environ.get('WIZARD_OWNER_LOGINS') or '').split(',') if x.strip()}
    return len(logins) == 1 and '@' in logins[0] and (not owners or logins[0].lower() in owners)


def _sw_send(h, code, doc):
    body = _sw_json.dumps(doc).encode()
    h.send_response(code)
    h.send_header('Content-Type', 'application/json')
    h.send_header('Cache-Control', 'no-store')
    h.send_header('Content-Length', str(len(body)))
    h.end_headers()
    if h.command != 'HEAD':
        h.wfile.write(body)


def _sw_handle(h):
    """Serve /api/switches (or /<app>/api/switches) and return True; False for every other request."""
    if not _SW_ROUTE.fullmatch(_sw_urlsplit(h.path).path):
        return False
    if h.command in ('GET', 'HEAD'):
        if not _sw_owner(h, False):
            _sw_send(h, 403, {'error': "Only this Wizard's owner can see these switches.", 'code': 'owner_only'})
        else:
            _sw_send(h, 200, switches_doc())
        return True
    if not _sw_owner(h, True):
        _sw_send(h, 403, {'error': "Only this Wizard's owner can change these switches.", 'code': 'owner_only'})
        return True
    try:
        if (h.headers.get('Content-Type') or '').split(';')[0].strip() != 'application/json':
            raise ValueError
        size = int(h.headers.get('Content-Length') or '0')
        if size <= 0 or size > 4096:
            raise ValueError
        body = _sw_json.loads(h.rfile.read(size))
        if not isinstance(body, dict) or not isinstance(body.get('id'), str) or not isinstance(body.get('on'), bool) \
                or set(body) - {'id', 'on'}:
            raise ValueError
    except (ValueError, TypeError):
        _sw_send(h, 400, {'error': 'Send JSON {"id": "...", "on": true|false}', 'code': 'invalid_input'})
        return True
    if body['id'] not in {s['id'] for s in SWITCHES}:
        _sw_send(h, 404, {'error': 'No such switch', 'code': 'unknown_switch'})
        return True
    try:
        _sw_send(h, 200, _sw_set(body['id'], body['on']))
    except OSError:
        _sw_send(h, 500, {'error': 'storage_failure'})
    return True


def wizard_switches_install(handler_cls):
    """Route the switch endpoint ahead of the app's own GET/HEAD/POST handlers."""
    for method in ('do_GET', 'do_HEAD', 'do_POST'):
        orig = getattr(handler_cls, method, None)
        if getattr(orig, '_wizard_switches', False):
            continue

        def wrapped(self, _orig=orig):
            if _sw_handle(self):
                return None
            if _orig is None:
                return self.send_error(501)
            return _orig(self)
        wrapped._wizard_switches = True
        setattr(handler_cls, method, wrapped)
    return handler_cls
# ---- end wizard.app-switches/1 ---------------------------------------------------------------------------------------

wizard_switches_install(Handler)


if __name__ == '__main__':
    manager = Manager(DATA)
    manager.start()
    ThreadingHTTPServer((os.environ.get('BIND', '127.0.0.1'), PORT), Handler).serve_forever()
