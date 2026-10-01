#!/usr/bin/env python3
"""Feedback (stateful) wallpaper previews: ping-pong CA shaders.

A feedback variant is defined by a shader pair in shaders/feedback/:

    <name>-ca.frag    one evolution step (reads state, writes state)
    <name>-comp.frag  composite (reads state, renders the display frame)

The CA step runs on a fixed cell grid (GRID_W x GRID_H); the composite
renders the state into the display FBO of the renderer's RenderContext,
so any display resolution works for free. State textures are RGBA8
(discrete automata) or RGBA16F (continuous automata) — see VARIANTS.

All GL calls run on the webserver's renderer thread (the GL context is
per-thread and all GL work is serialized through the job queue), so no
locking is needed here.

Mesa surfaceless quirk: glFramebufferTexture2D on a texture with no
allocated image returns INVALID_OPERATION and drops the attach, so both
state textures are allocated before their FBOs attach them.
"""
import ctypes
import glob
import math
import os
import random

import render  # same dir

GRID_W, GRID_H = 320, 180
DEFAULT_SEED = 20260001   # deterministic colonies across restarts

GL = dict(
    TEXTURE_2D=0x0DE1, RGBA8=0x8058, RGBA32F=0x8814,
    RGBA=0x1908, UNSIGNED_BYTE=0x1401, FLOAT=0x1406,
    FRAMEBUFFER=0x8D40, READ_FRAMEBUFFER=0x8CA8, COLOR_ATTACHMENT0=0x8CE0,
    FRAMEBUFFER_COMPLETE=0x8CD5, COLOR_BUFFER_BIT=0x4000,
    TRIANGLES=0x0004, TEXTURE0=0x84C0, TEXTURE1=0x84C1,
    NEAREST=0x2600, LINEAR=0x2601,
    # NOTE: MAG=0x2800, MIN=0x2801 (0x2802 is WRAP_S — easily confused)
    MAG_FILTER=0x2800, MIN_FILTER=0x2801,
    LINK_STATUS=0x8B82, INFO_LOG=0x8B84,
)

# Per-variant config.
#   internal  : state texture internal format (this Mesa ES build is not
#               color-renderable for RGBA16F — use RGBA32F for float state)
#   type      : upload type matching internal
#   seed      : seed generator name (see _seed_bytes)
#   defaults  : CA uniform defaults (override via ?u_<name>= query)
#   comp_samplers: composite sampler uniforms in unit order
#                  (unit 0 first), filter mode per unit
VARIANTS = {
    "life": {
        "internal": GL["RGBA8"],
        "type": GL["UNSIGNED_BYTE"],
        "seed": "soup",
        "defaults": {"u_decay": 0.93, "u_rain": 0.00006},
        "comp_samplers": [("u_lin", "linear"), ("u_near", "nearest")],
    },
    "mnca": {
        "internal": GL["RGBA32F"],
        "type": GL["FLOAT"],
        "seed": "blobs",
        "defaults": {
            # rule = (a dead-zone, b peak, c zero-crossing, d gain); a must
            # sit above the 0.06 ambient base so empty space stays inert.
            # "colony" set: separated self-organizing patches with true
            # dark gaps (32% of the field below 20/255) and internal
            # texture — the Softology bacteria-colony look. Higher a than
            # the dense-web settings keeps the colonies from fusing into
            # a connected lacework.
            "u_decay": 0.94,
            # ambient reseed: ~1 fresh 2x2 colony per ~90 generations in
            # dead space, so the steady state keeps breathing instead of
            # freezing into the web attractor
            "u_rain": 0.0001,
            "u_k1": [0.16, 0.48, 0.80, 1.0],   # disk r=2 (local)
            "u_k2": [0.16, 0.52, 0.88, 0.9],   # ring r=3 (mid)
            "u_k3": [0.20, 0.64, 0.98, 0.6],   # ring r=4 (long range)
            "u_w": [0.55, 0.35, 0.10],
        },
        "comp_samplers": [("u_state", "nearest")],
    },
}

CA_UNIFORMS = ("u_state", "u_grid", "u_frame", "u_decay", "u_rain",
               "u_k1", "u_k2", "u_k3", "u_w")
COMP_UNIFORMS = ("u_state", "u_lin", "u_near", "u_grid", "u_res")


def discover(shader_dir):
    """Feedback variant names present under shaders/feedback/."""
    fb = os.path.join(shader_dir, "feedback")
    if not os.path.isdir(fb):
        return []
    out = []
    for p in sorted(glob.glob(os.path.join(fb, "*-ca.frag"))):
        name = os.path.basename(p)[:-len("-ca.frag")]
        if os.path.exists(os.path.join(fb, name + "-comp.frag")):
            out.append(name)
    return out


def _feedback_dir(shader_dir):
    return os.path.join(shader_dir, "feedback")


# ---------------------------------------------------------------------------
# Seeds (pure Python — the webserver keeps its dependency surface small)
# ---------------------------------------------------------------------------
def _seed_soup(seed=DEFAULT_SEED):
    """life: random soup + glider/R-pentomino stamps (RGBA8)."""
    rnd = random.Random(seed)
    a = bytearray(GRID_W * GRID_H)
    for i in range(GRID_W * GRID_H):
        if rnd.random() < 0.065:
            a[i] = 1

    def stamp(cells, ox, oy):
        for cx, cy in cells:
            a[((oy + cy) % GRID_H) * GRID_W + (ox + cx) % GRID_W] = 1

    glider = [(1, 0), (2, 1), (0, 2), (1, 2), (2, 2)]
    rpent = [(1, 0), (0, 1), (1, 1), (1, 2), (2, 2)]
    stamp(glider, 30, 30)
    stamp(glider, 250, 120)
    stamp(glider, 180, 40)
    stamp(rpent, 90, 90)
    stamp(rpent, 240, 60)
    out = bytearray(GRID_W * GRID_H * 4)
    for i, v in enumerate(a):
        out[4 * i] = 255 * v      # R alive
        out[4 * i + 1] = 255 * v  # G energy
    return bytes(out)


def _seed_blobs(seed=DEFAULT_SEED, n=12):
    """mnca: smooth random blobs on a low base (RGBA32F: s, trail, 0, 0)."""
    import struct
    rnd = random.Random(seed)
    s = [0.06] * (GRID_W * GRID_H)
    for _ in range(n):
        cx = rnd.uniform(0, GRID_W)
        cy = rnd.uniform(0, GRID_H)
        r = rnd.uniform(4.0, 9.0)
        amp = rnd.uniform(0.30, 0.55)
        sig2 = 2.0 * (r * 0.55) ** 2
        x0, x1 = int(max(0, cx - 2 * r)), int(min(GRID_W, cx + 2 * r))
        y0, y1 = int(max(0, cy - 2 * r)), int(min(GRID_H, cy + 2 * r))
        for y in range(y0, y1):
            row = y * GRID_W
            for x in range(x0, x1):
                d2 = (x - cx) ** 2 + (y - cy) ** 2
                s[row + x] = min(1.0, s[row + x]
                                 + amp * math.exp(-d2 / sig2))
    vals = []
    for v in s:
        vals.append(v)
        vals.append(v * 0.6)   # trail a little under state
        vals.append(0.0)
        vals.append(0.0)
    return struct.pack("<%df" % len(vals), *vals)


_SEEDS = {"soup": _seed_soup, "blobs": _seed_blobs}


class FeedbackState:
    """One ping-pong CA state for a (variant, RenderContext) pair.

    GL objects here belong to ctx's EGL context; only the renderer thread
    may touch them.
    """

    def __init__(self, name, ctx, shader_dir):
        if name not in VARIANTS:
            raise KeyError("unknown feedback variant %r" % name)
        self.name = name
        self.cfg = VARIANTS[name]
        self.ctx = ctx
        self.fn = ctx._fn
        self.gen = 0
        # All GL state below belongs to ctx's EGL context — make it
        # current: the previous job may have left another context current.
        if not render.EGL.eglMakeCurrent(ctx._dpy, 0, 0, ctx._ctx):
            raise RuntimeError("eglMakeCurrent failed")
        fb = _feedback_dir(shader_dir)
        self.ca_path = os.path.join(fb, name + "-ca.frag")
        self.comp_path = os.path.join(fb, name + "-comp.frag")
        self.ca_src = open(self.ca_path, "rb").read()
        self.comp_src = open(self.comp_path, "rb").read()
        self.seed = DEFAULT_SEED
        self._mtimes = None
        self._ca_prog = None
        self._comp_prog = None
        self._ca_uni = {}
        self._comp_uni = {}

        f = self.fn
        # ensure the float uniform entrypoints are signature-bound:
        # render.py pre-binds 1f/2f; 3f/4f (vec3/vec4 CA params) would
        # otherwise be unbound, and unbound ctypes cannot convert floats
        f("glUniform1f", None, ctypes.c_int, ctypes.c_float)
        f("glUniform2f", None, ctypes.c_int, ctypes.c_float,
          ctypes.c_float)
        f("glUniform3f", None, ctypes.c_int, ctypes.c_float,
          ctypes.c_float, ctypes.c_float)
        f("glUniform4f", None, ctypes.c_int, ctypes.c_float,
          ctypes.c_float, ctypes.c_float, ctypes.c_float)

        # state FBOs: allocate both textures first, then attach (Mesa)
        self._tex = []
        self._fbo = []
        for i in range(2):
            t = ctypes.c_uint()
            f("glGenTextures")(1, ctypes.byref(t))
            fb_id = ctypes.c_uint()
            f("glGenFramebuffers")(1, ctypes.byref(fb_id))
            self._tex.append(t.value)
            self._fbo.append(fb_id.value)
        self._upload_seed(0)
        self._upload_seed(1)
        for i in range(2):
            f("glBindFramebuffer")(GL["FRAMEBUFFER"], self._fbo[i])
            f("glBindTexture")(GL["TEXTURE_2D"], self._tex[i])
            f("glFramebufferTexture2D")(
                GL["FRAMEBUFFER"], GL["COLOR_ATTACHMENT0"],
                GL["TEXTURE_2D"], self._tex[i], 0)
            st = f("glCheckFramebufferStatus")(GL["FRAMEBUFFER"])
            if st != GL["FRAMEBUFFER_COMPLETE"]:
                raise RuntimeError(
                    "feedback FBO %d incomplete 0x%x" % (i, st))

        # one sampler per filter mode (unit 0 is shared by both passes)
        self._smp = {}
        for mode in ("nearest", "linear"):
            s = ctypes.c_uint()
            f("glGenSamplers", None, ctypes.c_int,
              ctypes.POINTER(ctypes.c_uint))(1, ctypes.byref(s))
            flt = GL["NEAREST"] if mode == "nearest" else GL["LINEAR"]
            f("glSamplerParameteri", None, ctypes.c_uint,
              ctypes.c_uint, ctypes.c_int)(s.value, GL["MIN_FILTER"], flt)
            f("glSamplerParameteri")(s.value, GL["MAG_FILTER"], flt)
            self._smp[mode] = s.value

        # commit program for upload-flush draws (Mesa surfaceless quirk,
        # see _flush)
        vs = ctx._compile(render._WARMUP_VS, "vertex")
        fs = ctx._compile(render._WARMUP_FS, "fragment")
        self._commit_prog = self._link(vs, fs)

        self._recompile()
        self._flush()   # commit the initial seed uploads

    # -- setup --------------------------------------------------------------
    def _recompile(self):
        f = self.fn
        mt = (os.stat(self.ca_path).st_mtime_ns,
              os.stat(self.comp_path).st_mtime_ns)
        if mt == self._mtimes:
            return
        # re-read sources: edits to the shaders take effect without restart
        self.ca_src = open(self.ca_path, "rb").read()
        self.comp_src = open(self.comp_path, "rb").read()
        for prog in (self._ca_prog, self._comp_prog):
            if prog:
                f("glDeleteProgram", None, ctypes.c_uint)(prog)
        vs = self.ctx._compile(render.VERT_SRC, "vertex")
        self._ca_prog = self._link(vs,
                                   self.ctx._compile(self.ca_src, "fragment"))
        self._comp_prog = self._link(vs,
                                     self.ctx._compile(self.comp_src,
                                                       "fragment"))
        self._ca_uni = {}
        for u in CA_UNIFORMS:
            loc = f("glGetUniformLocation")(self._ca_prog, u.encode())
            if loc >= 0:
                self._ca_uni[u] = loc
        self._comp_uni = {}
        for u in COMP_UNIFORMS:
            loc = f("glGetUniformLocation")(self._comp_prog, u.encode())
            if loc >= 0:
                self._comp_uni[u] = loc
        if "u_grid" not in self._ca_uni:
            raise RuntimeError("CA shader missing u_grid")
        self._mtimes = mt

    def _link(self, vs, fs):
        f = self.fn
        prog = f("glCreateProgram")()
        f("glAttachShader")(prog, vs)
        f("glAttachShader")(prog, fs)
        f("glLinkProgram")(prog)
        ok = ctypes.c_int()
        f("glGetProgramiv")(prog, GL["LINK_STATUS"], ctypes.byref(ok))
        if not ok.value:
            ln = ctypes.c_int()
            f("glGetProgramiv")(prog, GL["INFO_LOG"], ctypes.byref(ln))
            log = ctypes.create_string_buffer(ln.value or 256)
            f("glGetProgramInfoLog")(prog, ln.value or 256, None, log)
            raise RuntimeError("link failed:\n%s"
                               % log.value.decode(errors="replace"))
        return prog

    def _upload_seed(self, which):
        f = self.fn
        if which == 0:
            data = _SEEDS[self.cfg["seed"]](self.seed)
        else:
            data = bytes(GRID_W * GRID_H * 4)
        p = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        f("glBindTexture")(GL["TEXTURE_2D"], self._tex[which])
        f("glTexImage2D")(GL["TEXTURE_2D"], 0, self.cfg["internal"],
                          GRID_W, GRID_H, 0, GL["RGBA"],
                          self.cfg["type"], p, None)

    def _flush(self):
        """Mesa surfaceless quirk: glTexImage2D data is only visible to
        sampling after at least one draw has run on the context since the
        upload (glClear/glFinish do not commit it; no GL error is set).
        One solid 1x1 draw into the spare state FBO commits pending
        uploads; the CA pass clears and redraws that FBO immediately."""
        f = self.fn
        f("glUseProgram")(self._commit_prog)
        f("glBindFramebuffer")(GL["FRAMEBUFFER"], self._fbo[1])
        f("glClearColor")(0.0, 0.0, 0.0, 1.0)
        f("glViewport")(0, 0, 1, 1)
        f("glClear")(GL["COLOR_BUFFER_BIT"])
        f("glDrawArrays")(GL["TRIANGLES"], 0, 3)

    # -- step ----------------------------------------------------------------
    def step(self, w, h, uniforms=None, reset=False, seed=None):
        """Advance one generation; composite into the display FBO and
        return the readback (RGBA bytes, top-first)."""
        f = self.fn
        ctx = self.ctx
        if not render.EGL.eglMakeCurrent(ctx._dpy, 0, 0, ctx._ctx):
            raise RuntimeError("eglMakeCurrent failed")
        self._recompile()
        if reset:
            if seed is not None:
                self.seed = seed
            self._upload_seed(0)
            self._upload_seed(1)
            self.gen = 0
            self._flush()   # commit the fresh uploads
        # variant defaults under caller overrides — callers (webserver,
        # make-gifs) may pass a bare step() and still get a working rule
        uniforms = dict(VARIANTS[self.name].get("defaults", {}))
        uniforms.update(uniforms or {})

        # CA pass: read tex[0], write fbo[1] (NEAREST on unit 0)
        f("glUseProgram")(self._ca_prog)
        f("glBindSampler")(0, self._smp["nearest"])
        f("glActiveTexture", None, ctypes.c_uint)(GL["TEXTURE0"])
        f("glBindTexture")(GL["TEXTURE_2D"], self._tex[0])
        f("glUniform1i")(self._ca_uni["u_state"], 0)
        f("glUniform2f")(self._ca_uni["u_grid"], float(GRID_W),
                         float(GRID_H))
        if "u_frame" in self._ca_uni:   # optional: not every CA uses time
            f("glUniform1f")(self._ca_uni["u_frame"], float(self.gen))
        for name, val in uniforms.items():
            if name not in self._ca_uni:
                continue
            vals = val if isinstance(val, (list, tuple)) else [val]
            if len(vals) == 1:
                f("glUniform1f")(self._ca_uni[name], float(vals[0]))
            elif len(vals) == 2:
                f("glUniform2f")(self._ca_uni[name],
                                 float(vals[0]), float(vals[1]))
            elif len(vals) == 3:
                f("glUniform3f")(self._ca_uni[name],
                                 *[float(v) for v in vals])
            elif len(vals) == 4:
                f("glUniform4f")(self._ca_uni[name],
                                 *[float(v) for v in vals])
            else:
                raise ValueError("bad uniform size for %s" % name)
        f("glBindFramebuffer")(GL["FRAMEBUFFER"], self._fbo[1])
        f("glViewport")(0, 0, GRID_W, GRID_H)
        # glClearColor before the first clear on a fresh context: on this
        # Mesa build the first clear+draw of a context only commits pending
        # texture uploads after a glClearColor call (matches render.py's
        # stateless render(), which is why it never hit this)
        f("glClearColor")(0.0, 0.0, 0.0, 1.0)
        f("glClear")(GL["COLOR_BUFFER_BIT"])
        f("glDrawArrays")(GL["TRIANGLES"], 0, 3)

        self._tex[0], self._tex[1] = self._tex[1], self._tex[0]
        self._fbo[0], self._fbo[1] = self._fbo[1], self._fbo[0]
        self.gen += 1

        # composite: new tex[0] -> display FBO at (w, h)
        f("glUseProgram")(self._comp_prog)
        for unit, (uname, mode) in enumerate(self.cfg["comp_samplers"]):
            if uname in self._comp_uni:
                f("glBindSampler")(unit, self._smp[mode])
                f("glUniform1i")(self._comp_uni[uname], unit)
        f("glBindTexture")(GL["TEXTURE_2D"], self._tex[0])
        if "u_grid" in self._comp_uni:
            f("glUniform2f")(self._comp_uni["u_grid"], float(GRID_W),
                             float(GRID_H))
        if "u_res" in self._comp_uni:
            f("glUniform2f")(self._comp_uni["u_res"], float(w), float(h))
        f("glBindFramebuffer")(GL["FRAMEBUFFER"], ctx._fbo)
        f("glViewport")(0, 0, w, h)
        f("glClearColor")(0.0, 0.0, 0.0, 1.0)
        f("glClear")(GL["COLOR_BUFFER_BIT"])
        f("glDrawArrays")(GL["TRIANGLES"], 0, 3)

        buf = (ctypes.c_ubyte * (w * h * 4))()
        f("glBindFramebuffer")(GL["READ_FRAMEBUFFER"], ctx._fbo)
        f("glReadPixels")(0, 0, w, h, GL["RGBA"], GL["UNSIGNED_BYTE"], buf)
        rows = w * 4
        out = bytearray(w * h * 4)
        for r in range(h):
            out[r * rows:(r + 1) * rows] = buf[(h - 1 - r) * rows:(h - r)
                                               * rows]
        return bytes(out)
