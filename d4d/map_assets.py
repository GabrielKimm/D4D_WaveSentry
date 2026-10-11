"""Loopback-only static assets for Chromium workers; never serves workspace files."""
import atexit
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from urllib.parse import unquote, urlsplit
from PySide6.QtCore import QFile, QIODevice

ROOT=Path(__file__).resolve().parents[1]/'assets/satellite'
_server=None


def asset_origin():
    global _server
    if _server is None:
        resource=QFile(':/qtwebchannel/qwebchannel.js')
        if not resource.open(QIODevice.ReadOnly):
            raise RuntimeError('Qt WebChannel script unavailable')
        channel_script=bytes(resource.readAll());resource.close()
        class Handler(SimpleHTTPRequestHandler):
            def do_GET(self):
                path=unquote(urlsplit(self.path).path)
                if path=='/qtwebchannel.js':
                    self.send_response(200);self.send_header('Content-Type','application/javascript')
                    self.send_header('Content-Length',str(len(channel_script)));self.end_headers()
                    self.wfile.write(channel_script);return
                target=(ROOT/path.lstrip('/')).resolve()
                if not target.is_relative_to(ROOT.resolve()):
                    self.send_error(403);return
                super().do_GET()
            def list_directory(self,path):
                self.send_error(404);return None
            def log_message(self,*args):
                pass
        _server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(ROOT)))
        _server.daemon_threads=True
        threading.Thread(target=_server.serve_forever,name='WaveSentry-MapAssets',daemon=True).start()
        def close_server():
            _server.shutdown()
            _server.server_close()
        atexit.register(close_server)
    return f'http://127.0.0.1:{_server.server_port}'
