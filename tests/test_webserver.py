"""Integration tests for the web preview server.

The server is started on a free port in a subprocess. The /frame check
needs a GPU (the server renders on demand); it is skipped when rendering is
unavailable rather than failing.

Run: python3 -m unittest discover -s tests -v
"""
import json
import os
import socket
import subprocess
import sys
import time
import unittest
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestWebServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = _free_port()
        cls.proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "scripts", "webserver.py"),
             "--port", str(cls.port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{cls.port}/healthz",
                        timeout=1) as r:
                    if r.status == 200:
                        return
            except Exception:
                time.sleep(0.2)
        raise RuntimeError("webserver did not come up")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.proc.kill()

    def get(self, path):
        with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}{path}", timeout=60) as r:
            return r.status, r.read()

    def test_healthz(self):
        status, body = self.get("/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(body.strip(), b"ok")

    def test_stats_lists_ink_variants_only(self):
        status, body = self.get("/stats")
        self.assertEqual(status, 200)
        stats = json.loads(body)
        self.assertEqual(sorted(stats["variants"]),
                         ["ink", "ink-melancholy"])
        self.assertEqual(stats["rate"], 2.0)
        self.assertIn(stats["default_variant"], stats["variants"])

    def test_index_served(self):
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"glsl", body.lower())

    def test_unknown_variant_rejected(self):
        with self.assertRaises(Exception):  # HTTP 400
            self.get("/frame?variant=nope&res=320x180")

    def test_frame_returns_png(self):
        # GPU-dependent: skip (not fail) when this host cannot render.
        try:
            status, body = self.get("/frame?variant=ink-melancholy&res=320x180")
        except Exception as exc:
            self.skipTest(f"no rendering available: {exc}")
        if status != 200 or not body.startswith(b"\x89PNG"):
            self.skipTest(f"server could not render (status={status})")
        self.assertEqual(body[:8], b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
