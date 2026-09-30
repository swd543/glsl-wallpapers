#!/usr/bin/env python3
"""Headless GLSL renderer for Plasma ShaderEffect wallpaper shaders.

Renders a `.frag` file (GLSL 440, Plasma ShaderEffect convention: uniform
block `buf` { qt_Matrix, qt_Opacity, time, resolution }) on the AMD iGPU
via EGL surfaceless + OpenGL ES 3.2 (Mesa/RADV). No window, no compositor,
no NVIDIA involvement.

The 440 source is transpiled to ESSL 3.00 at load time (layout-qualifier
rewrites + precision header); the math is unchanged.

CLI:
    python3 render.py <file.frag> <out.png> [time] [width] [height]
"""
import ctypes
import os
import re
import sys
import time

# Force Mesa-only EGL (AMD iGPU via RADV); never load the NVIDIA ICD.
MESA_VENDOR_JSON = "/usr/share/glvnd/egl_vendor.d/50_mesa.json"
if os.path.exists(MESA_VENDOR_JSON):
    os.environ.setdefault(
        "__EGL_VENDOR_LIBRARY_FILENAMES", MESA_VENDOR_JSON)

EGL = ctypes.CDLL("libEGL.so.1")
EGL.eglGetProcAddress.restype = ctypes.c_void_p
EGL.eglGetProcAddress.argtypes = [ctypes.c_char_p]
EGL.eglInitialize.restype = ctypes.c_uint
EGL.eglInitialize.argtypes = [ctypes.c_void_p,
                              ctypes.POINTER(ctypes.c_int),
                              ctypes.POINTER(ctypes.c_int)]
EGL.eglBindAPI.argtypes = [ctypes.c_uint]
EGL.eglChooseConfig.argtypes = [ctypes.c_void_p,
                                ctypes.POINTER(ctypes.c_int),
                                ctypes.POINTER(ctypes.c_void_p),
                                ctypes.c_int,
                                ctypes.POINTER(ctypes.c_int)]
EGL.eglCreateContext.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                 ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
EGL.eglCreateContext.restype = ctypes.c_void_p
EGL.eglMakeCurrent.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                               ctypes.c_void_p, ctypes.c_void_p]
EGL.eglMakeCurrent.restype = ctypes.c_uint
EGL.eglGetError.restype = ctypes.c_uint
EGL.eglGetError.argtypes = []

EGL_OPENGL_API = 0x000A
EGL_OPENGL_ES2_BIT = 0x0004
EGL_RENDERABLE_TYPE = 0x3040
EGL_SURFACE_TYPE = 0x3033
EGL_PBUFFER_BIT = 0x0001
EGL_NONE = 0x3038
EGL_VENDOR = 0x3053
EGL_VERSION = 0x3055
EGL_PLATFORM_SURFACELESS_MESA = 0x31D8

GL_FRAGMENT_SHADER = 0x8B30
GL_VERTEX_SHADER = 0x8B31
GL_COMPILE_STATUS = 0x8B81
GL_LINK_STATUS = 0x8B82
GL_INFO_LOG_LENGTH = 0x8B84
GL_ARRAY_BUFFER = 0x8892
GL_UNIFORM_BUFFER = 0x8A11
GL_UNIFORM_BLOCK = 0x8A3F
GL_BUFFER_STATIC_STORAGE = 0x85B2
GL_TRIANGLES = 0x0004
GL_FLOAT = 0x1406
GL_COLOR_BUFFER_BIT = 0x4000
GL_RGBA = 0x1908
GL_UNSIGNED_BYTE = 0x1401
GL_VERSION_ = 0x1F02
GL_VENDOR_ = 0x1F00
GL_RENDERER_ = 0x1F01
GL_TEXTURE_2D = 0x0DE1
GL_RGBA8 = 0x8058
GL_FRAMEBUFFER = 0x8D40
GL_READ_FRAMEBUFFER = 0x8CA8
GL_COLOR_ATTACHMENT0 = 0x8CE0
GL_FRAMEBUFFER_COMPLETE = 0x8CD5

VERT_SRC = (b"#version 310 es\n"
            b"const vec2 P[3] = vec2[3](vec2(-1.0, -1.0), vec2(3.0, -1.0),\n"
            b"                                  vec2(-1.0, 3.0));\n"
            b"out vec2 qt_TexCoord0;\n"
            b"void main() {\n"
            b"    int i = gl_VertexID;\n"
            b"    gl_Position = vec4(P[i], 0.0, 1.0);\n"
            b"    qt_TexCoord0 = P[i] * 0.5 + 0.5;\n"
            b"}\n")
# NOTE: no vertex attributes at all. The Mesa surfaceless driver on this
# machine breaks VBO/VAO attribute state (glBufferStorage/glVertexAttrib
# Pointer fail with INVALID_VALUE/INVALID_OPERATION), so the fullscreen
# triangle is generated in the vertex shader via gl_VertexID (ES 3.0 core).


def transpile_es(src: bytes) -> bytes:
    """GLSL 440 (Plasma ShaderEffect) -> ESSL 3.00. Math is untouched.

    The Plasma "buf" UBO is replaced by flat uniforms (u_time, u_resolution,
    u_opacity) because this Mesa surfaceless ES driver drops UBO introspection
    (block count 0 / no member locations). The shaders never use qt_Matrix.
    """
    text = src.decode("utf-8")
    text = re.sub(r"^#version\s+4\d\d\s*", "", text, count=1, flags=re.M)
    # in/out with layout qualifiers
    text = re.sub(r"layout\s*\(\s*location\s*=\s*\d+\s*\)\s*in\s+",
                  "in ", text)
    text = re.sub(r"layout\s*\(\s*location\s*=\s*\d+\s*\)\s*out\s+",
                  "out ", text)
    # gl_FragData[0] -> fragColor (ES has no gl_FragData)
    text = text.replace("gl_FragData[0]", "fragColor")
    # Plasma UBO block -> flat uniforms
    text = re.sub(
        r"layout\s*\([^)]*\)\s*uniform\s+buf\s*\{.*?\}\s*ubuf\s*;",
        "uniform float u_time;\nuniform vec2 u_resolution;\n"
        "uniform float u_opacity;",
        text, flags=re.S)
    text = text.replace("ubuf.qt_Opacity", "u_opacity")
    text = text.replace("ubuf.time", "u_time")
    text = text.replace("ubuf.resolution", "u_resolution")
    if "ubuf." in text:
        raise ValueError("unhandled ubuf member in shader source")
    out = ["#version 310 es\nprecision highp float;\nprecision highp int;\n"]
    for line in text.splitlines():
        if not line.lstrip().startswith("precision "):
            out.append(line + "\n")
    return "".join(out).encode("utf-8")


class RenderContext:
    """Owns the EGL/GL state. Create once, reuse for many renders."""

    def __init__(self, width: int = 1280, height: int = 720):
        self._gl = {}
        self._programs = {}
        self._dpy = None
        self._ctx = None

        gpde = ctypes.CFUNCTYPE(
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int))(
            ctypes.cast(EGL.eglGetProcAddress(
                b"eglGetPlatformDisplayEXT"), ctypes.c_void_p).value)
        self._dpy = gpde(EGL_PLATFORM_SURFACELESS_MESA, None, None)
        if not self._dpy:
            raise RuntimeError("eglGetPlatformDisplayEXT(surfaceless) failed")
        maj, min_ = ctypes.c_int(), ctypes.c_int()
        if not EGL.eglInitialize(self._dpy, ctypes.byref(maj),
                                 ctypes.byref(min_)):
            raise RuntimeError("eglInitialize failed 0x%x"
                               % EGL.eglGetError())
        EGL.eglBindAPI(0x0007)  # EGL_OPENGL_ES2_API

        a = (ctypes.c_int * 3)(EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT,
                               EGL_NONE)
        configs = (ctypes.c_void_p * 64)()
        ncfg = ctypes.c_int()
        if not EGL.eglChooseConfig(self._dpy, a, configs, 64,
                                   ctypes.byref(ncfg)) or not ncfg.value:
            raise RuntimeError("eglChooseConfig failed 0x%x"
                               % EGL.eglGetError())
        ctx_attribs = (ctypes.c_int * 5)(0x3098, 3, 0x30FB, 2, EGL_NONE)
        self._ctx = EGL.eglCreateContext(self._dpy, configs[0], None,
                                         ctx_attribs)
        if not self._ctx:
            raise RuntimeError("eglCreateContext failed 0x%x"
                               % EGL.eglGetError())
        if not EGL.eglMakeCurrent(self._dpy, 0, 0, self._ctx):
            raise RuntimeError("eglMakeCurrent failed 0x%x"
                               % EGL.eglGetError())

        self._init_gl()
        self._setup_fbo(width, height)
        self.gl_version = self._gl_str(GL_VERSION_).decode(errors="replace")
        self.gl_vendor = self._gl_str(GL_VENDOR_).decode(errors="replace")
        self.gl_renderer = self._gl_str(GL_RENDERER_).decode(
            errors="replace")
        if not self.gl_version.startswith("OpenGL ES 3"):
            raise RuntimeError(
                "expected OpenGL ES 3.x context, got: %s" % self.gl_version)

    # -- helpers --------------------------------------------------------
    def _fn(self, name, restype=None, *argtypes):
        if name in self._gl:
            return self._gl[name]
        f = ctypes.CFUNCTYPE(restype, *argtypes)(
            ctypes.cast(EGL.eglGetProcAddress(name.encode()),
                        ctypes.c_void_p).value)
        self._gl[name] = f
        return f

    def _gl_str(self, name):
        f = self._fn("glGetString", ctypes.c_void_p, ctypes.c_uint)
        return ctypes.string_at(f(name))

    def _init_gl(self):
        self._fn("glCreateShader", ctypes.c_uint, ctypes.c_uint)
        self._fn("glShaderSource", None, ctypes.c_uint, ctypes.c_int,
                 ctypes.POINTER(ctypes.c_char_p),
                 ctypes.POINTER(ctypes.c_int))
        self._fn("glCompileShader", None, ctypes.c_uint)
        self._fn("glGetShaderiv", None, ctypes.c_uint, ctypes.c_uint,
                 ctypes.POINTER(ctypes.c_int))
        self._fn("glGetShaderInfoLog", None, ctypes.c_uint, ctypes.c_int,
                 ctypes.POINTER(ctypes.c_int),
                 ctypes.POINTER(ctypes.c_char))
        self._fn("glCreateProgram", ctypes.c_uint)
        self._fn("glAttachShader", None, ctypes.c_uint, ctypes.c_uint)
        self._fn("glLinkProgram", None, ctypes.c_uint)
        self._fn("glGetProgramiv", None, ctypes.c_uint, ctypes.c_uint,
                 ctypes.POINTER(ctypes.c_int))
        self._fn("glGetProgramInfoLog", None, ctypes.c_uint, ctypes.c_int,
                 ctypes.POINTER(ctypes.c_int),
                 ctypes.POINTER(ctypes.c_char))
        self._fn("glGetAttachedShaders", None, ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_int))
        self._fn("glUseProgram", None, ctypes.c_uint)
        self._fn("glCreateBuffers", None, ctypes.c_uint,
                 ctypes.POINTER(ctypes.c_uint))
        self._fn("glBindBuffer", None, ctypes.c_uint, ctypes.c_uint)
        self._fn("glBufferStorage", None, ctypes.c_uint, ctypes.c_size_t,
                 ctypes.c_void_p, ctypes.c_uint)
        self._fn("glDeleteBuffer", None, ctypes.c_uint,
                 ctypes.POINTER(ctypes.c_uint))
        self._fn("glDeleteBuffers", None, ctypes.c_uint,
                 ctypes.POINTER(ctypes.c_uint))
        self._fn("glCreateVertexArrays", None, ctypes.c_uint,
                 ctypes.POINTER(ctypes.c_uint))
        self._fn("glBindVertexArray", None, ctypes.c_uint)
        self._fn("glVertexAttribPointer", None, ctypes.c_uint, ctypes.c_int,
                 ctypes.c_uint, ctypes.c_uint, ctypes.c_size_t,
                 ctypes.c_void_p)
        self._fn("glEnableVertexAttribArray", None, ctypes.c_uint)
        self._fn("glUniformBuffer", None, ctypes.c_uint, ctypes.c_uint)
        self._fn("glGetProgramResourceIndex", ctypes.c_uint, ctypes.c_uint,
                 ctypes.c_uint, ctypes.c_char_p)
        self._fn("glGetAttribLocation", ctypes.c_int, ctypes.c_uint,
                 ctypes.c_char_p)
        self._fn("glGetUniformLocation", ctypes.c_int, ctypes.c_uint,
                 ctypes.c_char_p)
        self._fn("glUniform1f", None, ctypes.c_int, ctypes.c_float)
        self._fn("glUniform2f", None, ctypes.c_int, ctypes.c_float,
                 ctypes.c_float)
        self._fn("glGenFramebuffers", None, ctypes.c_uint,
                 ctypes.POINTER(ctypes.c_uint))
        self._fn("glBindFramebuffer", None, ctypes.c_uint, ctypes.c_uint)
        self._fn("glGenTextures", None, ctypes.c_uint,
                 ctypes.POINTER(ctypes.c_uint))
        self._fn("glBindTexture", None, ctypes.c_uint, ctypes.c_uint)
        self._fn("glTexImage2D", None, ctypes.c_uint, ctypes.c_int,
                 ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                 ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p,
                 ctypes.c_void_p)
        self._fn("glFramebufferTexture2D", None, ctypes.c_uint,
                 ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
                 ctypes.c_int)
        self._fn("glCheckFramebufferStatus", ctypes.c_uint, ctypes.c_uint)
        self._fn("glDeleteTextures", None, ctypes.c_uint,
                 ctypes.POINTER(ctypes.c_uint))
        self._fn("glDeleteFramebuffers", None, ctypes.c_uint,
                 ctypes.POINTER(ctypes.c_uint))
        self._fn("glViewport", None, ctypes.c_int, ctypes.c_int,
                 ctypes.c_int, ctypes.c_int)
        self._fn("glClearColor", None, ctypes.c_float, ctypes.c_float,
                 ctypes.c_float, ctypes.c_float)
        self._fn("glClear", None, ctypes.c_uint)
        self._fn("glDrawArrays", None, ctypes.c_uint, ctypes.c_int,
                 ctypes.c_int)
        self._fn("glReadPixels", None, ctypes.c_int, ctypes.c_int,
                 ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint,
                 ctypes.c_void_p)
        self._fn("glFinish", None)

    def _setup_fbo(self, width, height):
        self.width, self.height = width, height
        tex = ctypes.c_uint()
        self._fn("glGenTextures")(1, ctypes.byref(tex))
        self._tex = tex.value
        self._fn("glBindTexture")(GL_TEXTURE_2D, tex.value)
        self._fn("glTexImage2D")(GL_TEXTURE_2D, 0, GL_RGBA8, width, height,
                                 0, GL_RGBA, GL_UNSIGNED_BYTE, None, None)
        fbo = ctypes.c_uint()
        self._fn("glGenFramebuffers")(1, ctypes.byref(fbo))
        self._fbo = fbo.value
        self._fn("glBindFramebuffer")(GL_FRAMEBUFFER, fbo.value)
        self._fn("glFramebufferTexture2D")(GL_FRAMEBUFFER,
                                           GL_COLOR_ATTACHMENT0,
                                           GL_TEXTURE_2D, tex.value, 0)
        status = self._fn("glCheckFramebufferStatus")(GL_FRAMEBUFFER)
        if status != GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError("FBO incomplete 0x%x" % status)

    # -- shaders ---------------------------------------------------------
    def _compile(self, src: bytes, kind: str) -> int:
        shader = self._fn("glCreateShader")(
            GL_FRAGMENT_SHADER if kind == "fragment" else GL_VERTEX_SHADER)
        src_ptr = ctypes.c_char_p(src)
        self._fn("glShaderSource")(shader, 1, ctypes.byref(src_ptr), None)
        self._fn("glCompileShader")(shader)
        ok = ctypes.c_int()
        self._fn("glGetShaderiv")(shader, GL_COMPILE_STATUS,
                                  ctypes.byref(ok))
        if not ok.value:
            ln = ctypes.c_int()
            self._fn("glGetShaderiv")(shader, GL_INFO_LOG_LENGTH,
                                      ctypes.byref(ln))
            log = ctypes.create_string_buffer(ln.value or 256)
            self._fn("glGetShaderInfoLog")(shader, ln.value or 256, None,
                                           log)
            raise RuntimeError(
                "compile failed (%s):\n%s"
                % (kind, log.value.decode(errors="replace")))
        return shader

    def program_for(self, frag_src: bytes, key: str) -> int:
        """Compile/link (cached) the fragment source, return program id."""
        if key in self._programs:
            return self._programs[key][0]
        vs = self._compile(VERT_SRC, "vertex")
        fs = self._compile(transpile_es(frag_src), "fragment")
        prog = self._fn("glCreateProgram")()
        self._fn("glAttachShader")(prog, vs)
        self._fn("glAttachShader")(prog, fs)
        self._fn("glLinkProgram")(prog)
        ok = ctypes.c_int()
        self._fn("glGetProgramiv")(prog, GL_LINK_STATUS,
                                   ctypes.byref(ok))
        if not ok.value:
            ln = ctypes.c_int()
            self._fn("glGetProgramiv")(prog, GL_INFO_LOG_LENGTH,
                                       ctypes.byref(ln))
            log = ctypes.create_string_buffer(ln.value or 256)
            self._fn("glGetProgramInfoLog")(prog, ln.value or 256, None,
                                            log)
            raise RuntimeError(
                "link failed:\n%s" % log.value.decode(errors="replace"))
        # Per-program uniform locations (flat uniforms, since this Mesa
        # surfaceless ES driver drops UBO introspection).
        self._fn("glUseProgram")(prog)
        self._uni_time = self._fn("glGetUniformLocation")(prog, b"u_time")
        self._uni_res = self._fn("glGetUniformLocation")(prog,
                                                          b"u_resolution")
        self._uni_op = self._fn("glGetUniformLocation")(prog, b"u_opacity")
        for label, loc in (("u_time", self._uni_time),
                           ("u_resolution", self._uni_res),
                           ("u_opacity", self._uni_op)):
            if loc == -1:
                raise RuntimeError("uniform %s not found" % label)
        self._programs[key] = (prog, self._uni_time, self._uni_res,
                               self._uni_op)
        return prog

    # -- render ----------------------------------------------------------
    def render(self, frag_src: bytes, t: float, key: str) -> bytes:
        """Render one frame; returns RGBA bytes (width*height*4, row-major,
        top row first)."""
        # The web server caches one RenderContext per resolution. Creating a
        # later context changes the thread's current EGL context, so always
        # reactivate this instance before touching its programs/FBO. Without
        # this, IDs from one context are used in another and only a corner of
        # larger frames may be drawn.
        if not EGL.eglMakeCurrent(self._dpy, 0, 0, self._ctx):
            raise RuntimeError("eglMakeCurrent failed 0x%x" % EGL.eglGetError())
        w, h = self.width, self.height
        prog = self.program_for(frag_src, key)
        _, u_time, u_res, u_op = self._programs[key]
        self._fn("glUseProgram")(prog)
        self._fn("glUniform1f")(u_time, t)
        self._fn("glUniform2f")(u_res, float(w), float(h))
        self._fn("glUniform1f")(u_op, 1.0)
        # Bind FBO for both draw and read (ES 3.x keeps them separate).
        self._fn("glBindFramebuffer")(GL_FRAMEBUFFER, self._fbo)
        self._fn("glBindFramebuffer")(GL_READ_FRAMEBUFFER, self._fbo)

        self._fn("glViewport")(0, 0, w, h)
        self._fn("glClearColor")(0.0, 0.0, 0.0, 1.0)
        self._fn("glClear")(GL_COLOR_BUFFER_BIT)
        self._fn("glDrawArrays")(GL_TRIANGLES, 0, 3)

        buf = (ctypes.c_ubyte * (w * h * 4))()
        self._fn("glReadPixels")(0, 0, w, h, GL_RGBA, GL_UNSIGNED_BYTE, buf)
        # flip to top-first
        out = bytearray(w * h * 4)
        rowsize = w * 4
        for r in range(h):
            out[r * rowsize:(r + 1) * rowsize] = (
                bytes(buf[(h - 1 - r) * rowsize:(h - r) * rowsize]))
        return bytes(out)

    def render_png(self, frag_src: bytes, t: float, key: str) -> bytes:
        """Render one frame and return PNG-encoded bytes (top-first)."""
        from io import BytesIO
        from PIL import Image
        rgba = self.render(frag_src, t, key=key)
        img = Image.frombytes("RGBA", (self.width, self.height), rgba)
        bio = BytesIO()
        img.save(bio, format="PNG")
        return bio.getvalue()


def render_file(frag_path: str, out_path: str, t: float = 12.0,
                width: int = 1280, height: int = 720) -> None:
    ctx = RenderContext(width, height)
    print("GL: %s | %s | %s" % (ctx.gl_vendor, ctx.gl_renderer,
                                " ".join(ctx.gl_version.split()[:2])),
          flush=True)
    src = open(frag_path, "rb").read()
    rgba = ctx.render(src, t, key=frag_path)
    from PIL import Image
    img = Image.frombytes("RGBA", (width, height), rgba)
    img.save(out_path)
    print("SAVED %s %dx%d t=%s" % (out_path, width, height, t), flush=True)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    t = float(sys.argv[3]) if len(sys.argv) > 3 else 12.0
    w = int(sys.argv[4]) if len(sys.argv) > 4 else 1280
    h = int(sys.argv[5]) if len(sys.argv) > 5 else 720
    render_file(sys.argv[1], sys.argv[2], t, w, h)
