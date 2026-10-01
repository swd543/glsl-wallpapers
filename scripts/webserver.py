#!/usr/bin/env python3
"""Web preview server for the GLSL lock-screen wallpapers.

Renders the project shaders (GLSL 440, Plasma ShaderEffect convention) on the
AMD iGPU (EGL surfaceless + ES 3.2, Mesa) and serves:

    GET /                      phone-friendly preview page
    GET /frame?variant=&res=   one rendered frame (PNG), on demand
    GET /stats                 JSON: iGPU busy %, VRAM, fps, process/system RAM

The GL context is per-thread, so a single renderer thread owns it; HTTP
handlers submit jobs through a queue.

Usage:
    python3 webserver.py [--port 8090]

No system changes: listens on 0.0.0.0:PORT (open the firewall port manually
if firewalld blocks it).
"""
import argparse
import json
import os
import queue
import re
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render  # noqa: E402  (render.py, same dir)
import feedback  # noqa: E402  (feedback.py, same dir)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHADER_DIR = os.path.join(ROOT, "shaders")
WEB_DIR = os.path.join(ROOT, "web")

# The AMD iGPU (card1) — the KWin compositor also runs on it, so busy% is
# card-wide.
DRM_CARD = "card1"
DRM = "/sys/class/drm/%s/device" % DRM_CARD


def variant_list():
    out = []
    for name in sorted(os.listdir(SHADER_DIR)):
        if name.endswith(".frag"):
            out.append(name[:-5])
    # stateful (ping-pong) variants live in shaders/feedback/
    out += feedback.discover(SHADER_DIR)
    return out


RESOLUTIONS = [(320, 180), (640, 360), (960, 540), (1280, 720), (1920, 1080)]
DEFAULT_RES = (1280, 720)
RATE = 2.0  # matches Plasma main.qml: FrameAnimation * animationRate 2.0


# --------------------------------------------------------------------------
# Stats
# --------------------------------------------------------------------------
def _read_int(path):
    try:
        with open(path) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def _meminfo():
    out = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                out[k] = int(v.strip().split()[0])  # kB
    except OSError:
        pass
    return out


def gpu_info():
    return {
        "busy_percent": _read_int(os.path.join(DRM, "gpu_busy_percent")),
        "vram_used_bytes": _read_int(os.path.join(DRM, "mem_info_vram_used")),
        "vram_total_bytes": _read_int(
            os.path.join(DRM, "mem_info_vram_total")),
    }


def proc_rss_kb():
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None


def stats_snapshot(renderer):
    mi = _meminfo()
    fps = renderer.fps()
    return {
        "wall": time.strftime("%Y-%m-%d %H:%M:%S"),
        "gpu": gpu_info(),
        "fps": round(fps, 2),
        "frames": renderer.frames,
        "rss_kb": proc_rss_kb(),
        "mem_total_kb": mi.get("MemTotal"),
        "mem_available_kb": mi.get("MemAvailable"),
        "variants": variant_list(),
        "default_variant": renderer.default_variant,
        "resolutions": ["%dx%d" % r for r in RESOLUTIONS],
        "rate": RATE,
    }


# --------------------------------------------------------------------------
# Renderer thread (owns the EGL context)
# --------------------------------------------------------------------------
class Renderer(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="gpu-render")
        self.q = queue.Queue()
        self._contexts = {}          # (w, h) -> render.RenderContext
        self._fb = {}                # (name, w, h) -> feedback.FeedbackState
        self._start = time.time()
        self._frame_times = []
        self.frames = 0
        self.default_variant = variant_list()[0] if variant_list() else None
        self.error = None

    # -- context cache ----------------------------------------------------
    def _ctx(self, w, h):
        key = (w, h)
        if key not in self._contexts:
            self._contexts[key] = render.RenderContext(w, h)
        return self._contexts[key]

    def _src(self, variant):
        return open(os.path.join(SHADER_DIR, variant + ".frag"), "rb").read()

    def fps(self):
        now = time.time()
        self._frame_times = [t for t in self._frame_times if now - t < 5.0]
        if len(self._frame_times) < 2:
            return 0.0
        return len(self._frame_times) / (now - self._frame_times[0])

    # -- loop ---------------------------------------------------------------
    def run(self):
        try:
            self._ctx(*DEFAULT_RES)  # warm up eagerly (also validates GL)
            c = self._contexts[DEFAULT_RES]
            self.log("ready: %s | %s" % (
                " ".join(c.gl_version.split()[:2]), c.gl_renderer))
        except Exception as e:  # noqa: BLE001
            self.error = "GL init failed: %s" % e
            self.log(self.error)
            return
        while True:
            job = self.q.get()
            if job is None:
                break
            kind = job[0]
            if kind == "frame":
                _, variant, w, h, reply = job
                try:
                    t = (time.time() - self._start) * RATE
                    path = os.path.join(SHADER_DIR, variant + ".frag")
                    src = open(path, "rb").read()
                    # mtime in the key: shader edits take effect without restart
                    key = "%s.%d" % (variant,
                                      os.stat(path).st_mtime_ns)
                    png = self._ctx(w, h).render_png(src, t, key=key)
                    self.frames += 1
                    self._frame_times.append(time.time())
                    reply.put(("ok", png))
                except Exception as e:  # noqa: BLE001
                    reply.put(("err", str(e)))
            elif kind == "feedback":
                _, name, w, h, gens, uniforms, reset, seed, reply = job
                try:
                    ctx = self._ctx(w, h)
                    key = (name, w, h)
                    st = self._fb.get(key)
                    if st is None or st.ctx is not ctx:
                        st = feedback.FeedbackState(name, ctx, SHADER_DIR)
                        self._fb[key] = st
                    params = dict(feedback.VARIANTS[name]["defaults"])
                    params.update(uniforms or {})
                    png = None
                    for i in range(gens):
                        rgba = st.step(w, h, params,
                                       reset=reset and i == 0,
                                       seed=seed)
                        png = self._rgba_png(rgba, w, h)
                    self.frames += 1
                    self._frame_times.append(time.time())
                    reply.put(("ok", png))
                except Exception as e:  # noqa: BLE001
                    reply.put(("err", str(e)))
            else:
                reply = job[1]
                reply.put(("ok", None))

    def _rgba_png(self, rgba, w, h):
        """Encode an RGBA readback as PNG bytes."""
        from io import BytesIO
        from PIL import Image
        img = Image.frombytes("RGBA", (w, h), rgba)
        bio = BytesIO()
        img.save(bio, format="PNG")
        return bio.getvalue()

    def log(self, msg):
        print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)

    def request_frame(self, variant, w, h, timeout=30.0):
        # Drop instead of queueing if renders are backing up; the client
        # polls again shortly and continuous time keeps the animation smooth.
        if self.q.qsize() > 3:
            raise RuntimeError("render queue busy (try again)")
        reply = queue.Queue()
        self.q.put(("frame", variant, w, h, reply))
        try:
            status, payload = reply.get(timeout=timeout)
        except queue.Empty:
            raise RuntimeError("render timeout")
        if status != "ok":
            raise RuntimeError(payload)
        return payload

    def request_frame_feedback(self, name, w, h, gens=1, uniforms=None,
                               reset=False, seed=None, timeout=30.0):
        if self.q.qsize() > 3:
            raise RuntimeError("render queue busy (try again)")
        reply = queue.Queue()
        self.q.put(("feedback", name, w, h, gens, uniforms, reset, seed,
                    reply))
        try:
            status, payload = reply.get(timeout=timeout)
        except queue.Empty:
            raise RuntimeError("render timeout")
        if status != "ok":
            raise RuntimeError(payload)
        return payload
def _qint(q, key):
    """Optional int query parameter (None if absent or bad)."""
    try:
        return int(q.get(key, [None])[0])
    except (TypeError, ValueError):
        return None


class Handler(BaseHTTPRequestHandler):
    renderer = None
    server_start = None

    def log_message(self, fmt, *args):
        pass  # keep it quiet; the renderer logs what matters

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        q = parse_qs(parsed.query)
        try:
            if parsed.path == "/":
                with open(os.path.join(WEB_DIR, "index.html"), "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            elif parsed.path == "/frame":
                variant = (q.get("variant") or [self.renderer.default_variant])[0]
                if variant not in variant_list():
                    self._send(400, b"unknown variant", "text/plain")
                    return
                res = (q.get("res") or ["%dx%d" % DEFAULT_RES])[0]
                m = re.fullmatch(r"(\d{2,4})x(\d{2,4})", res)
                if not m:
                    self._send(400, b"bad res", "text/plain")
                    return
                w, h = int(m.group(1)), int(m.group(2))
                if w > 2560 or h > 1440 or w < 160 or h < 90:
                    self._send(400, b"res out of range", "text/plain")
                    return
                if variant in feedback.discover(SHADER_DIR):
                    if "gens" in q:
                        try:
                            gens = max(1, min(200, int(q["gens"][0])))
                        except ValueError:
                            gens = 1
                    else:
                        gens = feedback.VARIANTS[variant].get("default_gens", 1)
                    uniforms = {}
                    for k, v in q.items():
                        if k in ("variant", "res", "t", "gens", "reset"):
                            continue
                        try:
                            vals = [float(x) for x in v[0].split(",")]
                        except ValueError:
                            continue
                        uniforms[k] = vals[0] if len(vals) == 1 else vals
                    png = self.renderer.request_frame_feedback(
                        variant, w, h, gens, uniforms, "reset" in q,
                        _qint(q, "seed"))
                else:
                    png = self.renderer.request_frame(variant, w, h)
                self._send(200, png, "image/png")
            elif parsed.path == "/stats":
                self._send(200, json.dumps(stats_snapshot(self.renderer))
                           .encode(), "application/json")
            elif parsed.path == "/healthz":
                body = ("ok" if not self.renderer.error
                        else self.renderer.error).encode()
                self._send(200 if not self.renderer.error else 503,
                           body, "text/plain")
            else:
                self._send(404, b"not found", "text/plain")
        except Exception as e:  # noqa: BLE001
            self._send(500, str(e).encode(), "text/plain")


def main():
    global SHADER_DIR, WEB_DIR
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--root", default=None,
                    help="repo root to serve (default: auto-detected)")
    args = ap.parse_args()
    if args.root:
        root = os.path.abspath(args.root)
        SHADER_DIR = os.path.join(root, "shaders")
        WEB_DIR = os.path.join(root, "web")

    if not variant_list():
        print("no shaders found in %s" % SHADER_DIR, file=sys.stderr)
        sys.exit(1)

    r = Renderer()
    r.start()
    # wait for GL warm-up
    for _ in range(100):
        if r.error or r._contexts:
            break
        time.sleep(0.2)
    if r.error:
        print(r.error, file=sys.stderr)
        sys.exit(1)

    Handler.renderer = r
    Handler.server_start = time.time()
    httpd = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    httpd.daemon_threads = True

    def _stop(signum, frame):
        # shutdown() blocks until serve_forever returns, so it must run
        # off the (interrupted) main thread — calling it directly here
        # deadlocks.
        r.q.put(None)
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    print("wallpaper preview on http://0.0.0.0:%d  (variants: %s)"
          % (args.port, ", ".join(variant_list())), flush=True)
    try:
        httpd.serve_forever()
    finally:
        r.q.put(None)


if __name__ == "__main__":
    main()
