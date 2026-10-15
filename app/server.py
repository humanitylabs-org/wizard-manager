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


if __name__ == '__main__':
    manager = Manager(DATA)
    manager.start()
    ThreadingHTTPServer((os.environ.get('BIND', '127.0.0.1'), PORT), Handler).serve_forever()
