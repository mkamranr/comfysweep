import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Point the process internals at a throwaway tree BEFORE the app is imported.
_TMP = tempfile.mkdtemp(prefix="comfysweep-test-")
os.environ["COMFYSWEEP_DATA_DIR"] = os.path.join(_TMP, "data")
os.environ["COMFYSWEEP_HOST_ROOT"] = os.path.join(_TMP, "host")
os.environ["COMFYSWEEP_NO_SCHEDULER"] = "1"
os.makedirs(os.environ["COMFYSWEEP_HOST_ROOT"], exist_ok=True)

from app import bootstrap, db, settings as S  # noqa: E402


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    """A clean database and host tree for every test."""
    data, host = tmp_path / "data", tmp_path / "host"
    host.mkdir()
    for d in ("output", "input", "temp"):
        (host / "ComfyUI" / d).mkdir(parents=True)
    monkeypatch.setattr(bootstrap, "DATA_DIR", str(data))
    monkeypatch.setattr(bootstrap, "HOST_ROOT", str(host))
    db.reset_cache()
    yield {"host": host, "out": host / "ComfyUI" / "output",
           "inp": host / "ComfyUI" / "input", "tmp": host / "ComfyUI" / "temp"}
    db.reset_cache()


def configure(paths, **over):
    s = S.Settings()
    s.comfy_url = over.pop("comfy_url", "http://127.0.0.1:59999")
    s.timezone = over.pop("timezone", "Asia/Dubai")
    s.safety.dry_run_only = over.pop("dry_run_only", False)
    s.folders["output"].path = str(paths["out"])
    s.folders["output"].enabled = True
    s.folders["output"].keep_days = over.pop("keep_days", 1)
    s.folders["input"].path = str(paths["inp"])
    s.folders["temp"].path = str(paths["tmp"])
    for k, v in over.items():
        setattr(s.safety, k, v)
    S.save(s)
    return s


def touch(path, when, size=100):
    path = str(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x" * size)
    os.utime(path, (when, when))


class ComfyStub(object):
    """A fake ComfyUI: GET /queue, /history, /view."""

    def __init__(self):
        self.history, self.files, self.views = {}, set(), []
        self.queue = {"queue_running": [], "queue_pending": []}
        stub = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="application/json"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                u = urllib.parse.urlsplit(self.path)
                q = urllib.parse.parse_qs(u.query)
                if u.path == "/queue":
                    return self._send(200, json.dumps(stub.queue).encode())
                if u.path == "/history":
                    return self._send(200, json.dumps(stub.history).encode())
                if u.path == "/view":
                    fn = (q.get("filename") or [""])[0]
                    stub.views.append(fn)
                    if fn in stub.files:
                        return self._send(200, b"P" * 2048, "image/png")
                    return self._send(404, b"{}")
                return self._send(404, b"{}")

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]

    @staticmethod
    def entry(fn, sub="", typ="output"):
        return {"outputs": {"9": {"images": [{"filename": fn, "subfolder": sub,
                                              "type": typ}]}}}


@pytest.fixture
def comfy():
    c = ComfyStub()
    yield c
    c.srv.shutdown()


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP, ignore_errors=True)
