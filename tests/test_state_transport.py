"""Real HTTP state transport against isolated app data; never a live upstream."""
import gzip
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from unittest.mock import patch
from http.server import ThreadingHTTPServer
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import server
from projects import ProjectManager
from test_manager import FakeAPI, FakeReadySource

class TransportTests(unittest.TestCase):
    def test_gzip_and_compact_state_over_real_http(self):
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {'MANAGER_READY_DB':''}):
            prefs=Path(root)/'prefs.json';prefs.write_text(json.dumps({'spaces':[{'id':'alpha','name':'Alpha','threads':[]}]}))
            api=FakeAPI()
            manager=ProjectManager(root,prefs_path=prefs,request=api,ready_source=FakeReadySource())
            with manager.connect() as c:
                for i in range(65):
                    c.execute("INSERT INTO messages(role,text,created,project_id) VALUES ('user',?,?,'alpha')",('Full paragraph. '*40,i))
            class Quiet(server.Handler):
                def log_message(self,*args): pass
            with patch.object(server,'manager',manager), patch.object(server,'TRUSTED_HOSTS',{'fixture'}):
                http=ThreadingHTTPServer(('127.0.0.1',0),Quiet)
                worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start()
                try:
                    req=Request('http://127.0.0.1:'+str(http.server_port)+'/api/state?project_id=alpha',headers={'Host':'fixture','Accept-Encoding':'gzip'})
                    with urlopen(req) as response:
                        compressed=response.read();self.assertEqual(response.headers['Content-Encoding'],'gzip');self.assertEqual(response.headers['Vary'],'Accept-Encoding')
                    payload=gzip.decompress(compressed);value=json.loads(payload)
                    self.assertLess(len(payload),30000);self.assertLess(len(compressed),len(payload))
                    self.assertTrue(value['has_older']);self.assertLessEqual(len(value['messages']),50)
                    self.assertNotIn('threads',value);self.assertNotIn('worker_index',value)
                    self.assertEqual(api.calls,[])
                finally:
                    http.shutdown();worker.join();http.server_close()
