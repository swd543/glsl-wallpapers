#!/usr/bin/env python3
"""Feedback Game of Life preview (ping-pong FBOs) on the AMD iGPU.

Runs the two-pass Life shaders (shaders/feedback/life-ca.frag +
life-comp.frag) through the same Mesa/EGL surfaceless ES 3.2 context as
render.py:

  per frame:
    1. CA pass     : stateA -> stateB   (one Conway generation, 8 taps)
    2. composite   : stateB -> display  (merge bloom + dark palette)
    3. readback    : display FBO -> PNG/GIF frame
    (swap A/B)

This is the design-iteration tool for the Android app's ping-pong port;
Plasma's QSB path is single-pass and cannot host it.

CLI:
    python3 scripts/life-preview.py [frames=300] [decay=0.93]
                                   [rain=0.00006] [outdir=/tmp/life1]
"""
import ctypes
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# grid / display
GW, GH = 320, 180          # cells (4 px per cell at 1280x720)
DW, DH = 1280, 720
GIF_W, GIF_H = 640, 360

GL_TEXTURE0 = 0x84C0
GL_TEXTURE1 = 0x84C1
GL_NEAREST = 0x2600
GL_LINEAR = 0x2601
GL_TEXTURE_MIN_FILTER = 0x2802
GL_TEXTURE_MAG_FILTER = 0x2801

GL_RGBA8 = 0x8058
GL_RGBA = 0x1908
GL_UNSIGNED_BYTE = 0x1401
GL_COLOR_BUFFER_BIT = 0x4000
GL_FRAMEBUFFER = 0x8D40


def gl2(name):
    return GL_TEXTURE0 + name


class LifePreview:
    def __init__(self):
        self.ctx = render.RenderContext(DW, DH)
        print("GL: %s | %s | %s" % (self.ctx.gl_vendor,
                                    self.ctx.gl_renderer,
                                    " ".join(
                                        self.ctx.gl_version.split()[:2])),
              flush=True)
        self._gl = self.ctx._fn
        self._ca = self._program(
            open(os.path.join(ROOT, "shaders/feedback/life-ca.frag"),
                 "rb").read(),
            ["u_state", "u_grid", "u_frame", "u_decay", "u_rain"])
        self._comp = self._program(
            open(os.path.join(ROOT, "shaders/feedback/life-comp.frag"),
                 "rb").read(),
            ["u_lin", "u_near", "u_grid", "u_res"])

        # samplers: unit0 = bilinear, unit1 = nearest
        self._gl("glGenSamplers", None, ctypes.c_int,
                 ctypes.POINTER(ctypes.c_uint))
        smp = (ctypes.c_uint * 2)()
        self._gl("glGenSamplers")(2, smp)
        self._gl("glBindSampler", None, ctypes.c_uint, ctypes.c_uint)
        self._gl("glSamplerParameteri", None, ctypes.c_uint,
                 ctypes.c_uint, ctypes.c_int)
        self._gl("glBindSampler")(0, smp[0])
        self._gl("glSamplerParameteri")(smp[0], GL_TEXTURE_MIN_FILTER,
                                        GL_LINEAR)
        self._gl("glSamplerParameteri")(smp[0], GL_TEXTURE_MAG_FILTER,
                                        GL_LINEAR)
        self._gl("glBindSampler")(1, smp[1])
        self._gl("glSamplerParameteri")(smp[1], GL_TEXTURE_MIN_FILTER,
                                        GL_NEAREST)
        self._gl("glSamplerParameteri")(smp[1], GL_TEXTURE_MAG_FILTER,
                                        GL_NEAREST)

        # two state FBOs (ping/pong).
        # Mesa surfaceless quirk: glFramebufferTexture2D on a texture with
        # no allocated image returns INVALID_OPERATION and the attach is
        # dropped, so allocate both texture images BEFORE attaching.
        self._state = []
        for i in range(2):
            tex = ctypes.c_uint()
            self._gl("glGenTextures")(1, ctypes.byref(tex))
            self._gl("glBindTexture")(0x0DE1, tex.value)
            fbo = ctypes.c_uint()
            self._gl("glGenFramebuffers")(1, ctypes.byref(fbo))
            self._state.append((tex.value, fbo.value))

        self._seed_texture()  # tex0 = seed, tex1 = zeros (allocates both)
        for i in range(2):
            tex, fbo = self._state[i]
            self._gl("glBindFramebuffer")(GL_FRAMEBUFFER, fbo)
            self._gl("glBindTexture")(0x0DE1, tex)
            self._gl("glFramebufferTexture2D", None,
                     ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
                     ctypes.c_uint, ctypes.c_int)(
                GL_FRAMEBUFFER, 0x8CE0, 0x0DE1, tex, 0)
            status = self._gl("glCheckFramebufferStatus")(GL_FRAMEBUFFER)
            if status != 0x8CD5:
                raise RuntimeError("state FBO %d incomplete 0x%x"
                                   % (i, status))
        self._bind_fbo(self._state[0][1])

    # -- setup ----------------------------------------------------------
    def _program(self, frag_src, uniforms):
        ctx = self.ctx
        vs = ctx._compile(render.VERT_SRC, "vertex")
        fs = ctx._compile(frag_src, "fragment")
        prog = self._gl("glCreateProgram")()
        self._gl("glAttachShader")(prog, vs)
        self._gl("glAttachShader")(prog, fs)
        self._gl("glLinkProgram")(prog)
        ok = ctypes.c_int()
        self._gl("glGetProgramiv")(prog, 0x8B82, ctypes.byref(ok))
        if not ok.value:
            ln = ctypes.c_int()
            self._gl("glGetProgramiv")(prog, 0x8B84, ctypes.byref(ln))
            log = ctypes.create_string_buffer(ln.value or 256)
            self._gl("glGetProgramInfoLog")(prog, ln.value or 256, None, log)
            raise RuntimeError("link failed:\n%s"
                               % log.value.decode(errors="replace"))
        locs = {}
        for u in uniforms:
            locs[u] = self._gl("glGetUniformLocation")(prog, u.encode())
            if locs[u] == -1:
                raise RuntimeError("uniform %s not found" % u)
        return (prog, locs)

    def _seed_texture(self):
        """Upload the seed into state texture 0 and zeros into texture 1."""
        alive = (np.random.random((GH, GW)) < 0.065)

        def stamp(cells, ox, oy):
            for cx, cy in cells:
                alive[(oy + cy) % GH, (ox + cx) % GW] = True

        glider = [(1, 0), (2, 1), (0, 2), (1, 2), (2, 2)]
        rpent = [(1, 0), (0, 1), (1, 1), (1, 2), (2, 2)]
        stamp(glider, 30, 30)
        stamp(glider, 250, 120)
        stamp(glider, 180, 40)
        stamp(rpent, 90, 90)
        stamp(rpent, 240, 60)

        nb = sum(np.roll(np.roll(alive, dy, axis=0), dx, axis=1)
                 for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                 if (dx, dy) != (0, 0))
        state = np.dstack([
            alive * 255, alive * 255,
            np.clip(nb, 0, 255).astype(np.uint8),
            np.full((GH, GW), 255, np.uint8),
        ]).astype(np.uint8)
        data = (ctypes.c_ubyte * state.size).from_buffer_copy(
            state.tobytes())
        self._gl("glBindTexture")(0x0DE1, self._state[0][0])
        self._gl("glTexImage2D")(0x0DE1, 0, GL_RGBA8, GW, GH, 0, GL_RGBA,
                                 GL_UNSIGNED_BYTE, data, None)
        zeros = (ctypes.c_ubyte * (GW * GH * 4))()
        self._gl("glBindTexture")(0x0DE1, self._state[1][0])
        self._gl("glTexImage2D")(0x0DE1, 0, GL_RGBA8, GW, GH, 0, GL_RGBA,
                                 GL_UNSIGNED_BYTE, zeros, None)

    def _bind_fbo(self, fbo):
        self._gl("glBindFramebuffer")(GL_FRAMEBUFFER, fbo)

    def _bind_state(self, idx):
        tex, _ = self._state[idx]
        self._gl("glBindTexture")(0x0DE1, tex)

    def _readback(self):
        buf = (ctypes.c_ubyte * (DW * DH * 4))()
        self._gl("glReadPixels")(0, 0, DW, DH, GL_RGBA, GL_UNSIGNED_BYTE,
                                 buf)
        rows = DW * 4
        out = bytearray(DW * DH * 4)
        for r in range(DH):
            out[r * rows:(r + 1) * rows] = bytes(
                buf[(DH - 1 - r) * rows:(DH - r) * rows])
        return np.frombuffer(out, np.uint8).reshape(DH, DW, 4)

    # -- frame ----------------------------------------------------------
    def frame(self, f, decay, rain):
        ctx = self.ctx
        if not render.EGL.eglMakeCurrent(ctx._dpy, 0, 0, ctx._ctx):
            raise RuntimeError("eglMakeCurrent failed")

        # 1. CA pass: state[idx] -> state[1-idx]
        prog, u = self._ca
        self._gl("glUseProgram")(prog)
        self._gl("glActiveTexture", None, ctypes.c_uint)(GL_TEXTURE0)
        self._bind_state(0)
        self._gl("glUniform1i")(u["u_state"], 0)
        self._gl("glUniform2f")(u["u_grid"], float(GW), float(GH))
        self._gl("glUniform1f")(u["u_frame"], float(f))
        self._gl("glUniform1f")(u["u_decay"], decay)
        self._gl("glUniform1f")(u["u_rain"], rain)
        self._bind_fbo(self._state[1][1])
        self._gl("glViewport")(0, 0, GW, GH)
        self._gl("glClearColor")(0.0, 0.0, 0.0, 1.0)
        self._gl("glClear")(GL_COLOR_BUFFER_BIT)
        self._gl("glDrawArrays")(0x0004, 0, 3)

        # 2. composite: state[1-idx] -> display fbo
        prog, u = self._comp
        self._gl("glUseProgram")(prog)
        self._gl("glActiveTexture", None, ctypes.c_uint)(GL_TEXTURE0)
        self._bind_state(1)
        self._gl("glUniform1i")(u["u_lin"], 0)
        self._gl("glUniform1i")(u["u_near"], 1)
        self._gl("glUniform2f")(u["u_grid"], float(GW), float(GH))
        self._gl("glUniform2f")(u["u_res"], float(DW), float(DH))
        self._bind_fbo(ctx._fbo)
        self._gl("glViewport")(0, 0, DW, DH)
        self._gl("glClear")(GL_COLOR_BUFFER_BIT)
        self._gl("glDrawArrays")(0x0004, 0, 3)

        out = self._readback()
        # swap ping/pong
        self._state[0], self._state[1] = self._state[1], self._state[0]
        return out


def main():
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    decay = float(sys.argv[2]) if len(sys.argv) > 2 else 0.93
    rain = float(sys.argv[3]) if len(sys.argv) > 3 else 0.00006
    outdir = sys.argv[4] if len(sys.argv) > 4 else "/tmp/life1"
    os.makedirs(outdir, exist_ok=True)

    lp = LifePreview()
    stills = {}
    gif_frames = []
    for f in range(frames):
        img = lp.frame(f, decay, rain)
        if (f + 1) % 50 == 0:
            print("frame %d/%d  mean=%.2f" % (f + 1, frames,
                                              img[..., :3].mean()),
                  flush=True)
        if (f + 1) in (90, 210, 300):
            stills[f + 1] = img
        if (f + 1) % 6 == 0:
            rgb = Image.frombytes("RGB", (DW, DH),
                                  img[:, :, :3].tobytes())
            gif_frames.append(
                rgb.resize((GIF_W, GIF_H), Image.BILINEAR))

    # stills
    for f, img in stills.items():
        p = os.path.join(outdir, "still-%d.png" % f)
        Image.frombytes("RGB", (DW, DH), img[:, :, :3].tobytes()).save(p)
        print("SAVED", p)

    # zoom crop of the busiest quadrant of the last still
    last = stills[max(stills)]
    lum = last[:, :, :3].astype(np.float32).mean(axis=2)
    q = (0, 1)
    best = -1.0
    for r in range(2):
        for c in range(2):
            m = lum[r * DH // 2:(r + 1) * DH // 2,
                    c * DW // 2:(c + 1) * DW // 2].mean()
            if m > best:
                best, q = m, (r, c)
    r, c = q
    crop = last[r * DH // 2:(r + 1) * DH // 2,
                c * DW // 2:(c + 1) * DW // 2, :3]
    p = os.path.join(outdir, "zoom.png")
    Image.frombytes("RGB", (DW // 2, DH // 2), crop.tobytes()).resize(
        (DW, DH), Image.NEAREST).save(p)
    print("SAVED", p)

    # gif (palette from first frame)
    if gif_frames:
        pal = gif_frames[0].convert("P", palette=Image.ADAPTIVE, colors=256)
        pframes = [f.convert("P", palette=pal) for f in gif_frames]
        p = os.path.join(outdir, "life.gif")
        pframes[0].save(p, format="GIF", save_all=True,
                        append_images=pframes[1:], duration=66, loop=0)
        print("SAVED %s (%d frames, %d KB)"
              % (p, len(pframes), os.path.getsize(p) // 1024))


if __name__ == "__main__":
    main()
