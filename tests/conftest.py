"""Servidor HTTP local con los fixtures para probar el motor sin salir a internet."""
from __future__ import annotations

import functools
import socket
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):  # silenciar
        pass

    def end_headers(self):
        # Las URLs de detalle no llevan .html en los fixtures: /author/ana -> author/ana.html
        super().end_headers()

    def translate_path(self, path):
        p = super().translate_path(path)
        if not Path(p).exists() and Path(p + ".html").exists():
            return p + ".html"
        return p


@pytest.fixture(scope="session")
def site_server():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    handler = functools.partial(_Quiet, directory=str(FIXTURES / "site"))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()


@pytest.fixture
def site_yaml(site_server, tmp_path):
    text = (FIXTURES / "site.yaml").read_text(encoding="utf-8").replace("http://127.0.0.1:PORT", site_server)
    p = tmp_path / "site.yaml"
    p.write_text(text, encoding="utf-8")
    return p


@pytest.fixture
def db_url(tmp_path):
    return f"sqlite:///{tmp_path / 'test.db'}"
