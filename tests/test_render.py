"""GPU integration tests for the headless renderer and the shaders.

These need a Mesa/EGL-capable GPU. They are skipped (not failed) when the
environment cannot create a render context, so the suite stays green on
machines without a GPU.

Run: python3 -m unittest discover -s tests -v
"""
import os
import struct
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHADER_DIR = os.path.join(ROOT, "shaders")
sys.path.insert(0, os.path.join(ROOT, "scripts"))

try:
    import render
    _PROBE = render.RenderContext(640, 360)
    _PROBE.render(open(os.path.join(SHADER_DIR, "ink.frag"), "rb").read(),
                  4.0, key="probe")
    _SKIP = ""
except Exception as exc:  # no GPU / no EGL / Mesa not present
    render = None
    _PROBE = None
    _SKIP = str(exc)


def shader_names():
    return sorted(n[:-5] for n in os.listdir(SHADER_DIR)
                  if n.endswith(".frag"))


@unittest.skipIf(render is None, f"no EGL render context: {_SKIP}")
class TestRenderer(unittest.TestCase):
    W, H = 640, 360

    @classmethod
    def setUpClass(cls):
        cls.ctx = render.RenderContext(cls.W, cls.H)
        cls.srcs = {n: open(os.path.join(SHADER_DIR, n + ".frag"), "rb").read()
                    for n in shader_names()}

    def test_context_reports_egl(self):
        self.assertTrue(self.ctx.gl_version.startswith("OpenGL ES 3"),
                        self.ctx.gl_version)

    def test_frames_are_not_black(self):
        for name, src in self.srcs.items():
            rgba = self.ctx.render(src, 8.0, key=f"black-{name}")
            total, n = 0, 0
            for y in range(0, self.H, 24):
                row = rgba[y * self.W * 4:(y + 1) * self.W * 4]
                for x in range(0, self.W, 24):
                    px = row[x * 4:x * 4 + 3]
                    total += max(px)
                    n += 1
            self.assertGreater(total / n, 4.0,
                               f"{name}: frame is effectively black")

    def test_frames_are_dark_enough_for_lockscreen(self):
        # These are dark-by-design lock/login wallpapers. Budgets are the
        # measured design values (mean max-channel over the frame, fraction
        # of pixels above 240): ink-melancholy is near-black; ink is the
        # brighter gold/white-on-green reference variant.
        budgets = {"ink": (200, 0.30), "ink-melancholy": (80, 0.02)}
        for name, src in self.srcs.items():
            if name not in budgets:
                continue
            mean_cap, hot_cap = budgets[name]
            rgba = self.ctx.render(src, 8.0, key=f"dark-{name}")
            total, hot, n = 0, 0, 0
            for y in range(0, self.H, 12):
                row = rgba[y * self.W * 4:(y + 1) * self.W * 4]
                for x in range(0, self.W, 12):
                    c = max(row[x * 4:x * 4 + 3])
                    total += c
                    hot += c > 240
                    n += 1
            self.assertLess(total / n, mean_cap,
                            f"{name}: mean max-channel too bright")
            self.assertLess(hot / n, hot_cap,
                            f"{name}: too many white-hot pixels")

    def test_animation_progresses(self):
        for name, src in self.srcs.items():
            a = self.ctx.render(src, 4.0, key=f"anim-{name}")
            # 1.5 s of shader time (the QML clock feeds ubuf.time*2.0)
            b = self.ctx.render(src, 4.0 + 3.0 / 2.0, key=f"anim-{name}")
            same = sum(1 for x, y in zip(a[::199], b[::199]) if x == y)
            self.assertLess(same, len(a) // 199,
                            f"{name}: frame identical over 1.5s of shader time")

    def test_render_png_roundtrip(self):
        png = self.ctx.render_png(self.srcs["ink-melancholy"], 8.0,
                                  key="png-check")
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        w, h = struct.unpack(">II", png[16:24])
        self.assertEqual((w, h), (self.W, self.H))

    def test_render_budget(self):
        # The ink family must stay well under budget: 150 ms ceiling at
        # 640x360 (includes CPU readback) guards against accidental
        # blowups without being sensitive to machine variance.
        src = self.srcs["ink-melancholy"]
        self.ctx.render(src, 4.0, key="budget")
        t0 = time.perf_counter()
        for i in range(3):
            self.ctx.render(src, 4.0 + i, key="budget")
        ms = (time.perf_counter() - t0) * 1000.0 / 3.0
        self.assertLess(ms, 150.0, f"ink-melancholy took {ms:.0f} ms/frame")


if __name__ == "__main__":
    unittest.main()
