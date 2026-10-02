"""Structural tests for the GLSL sources and QML templates (no GPU needed).

Run: python3 -m unittest discover -s tests -v
"""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHADER_DIR = os.path.join(ROOT, "shaders")
TEMPLATE = os.path.join(ROOT, "templates", "main.qml.in")
TIMER_TEMPLATE = os.path.join(ROOT, "templates", "main-timer.qml.in")

sys.path.insert(0, os.path.join(ROOT, "scripts"))
import render  # noqa: E402


def shader_sources():
    out = {}
    for name in sorted(os.listdir(SHADER_DIR)):
        if name.endswith(".frag"):
            out[name[:-5]] = open(os.path.join(SHADER_DIR, name)).read()
    return out


class TestPlasmaConventions(unittest.TestCase):
    """Every shader must follow the Plasma ShaderEffect convention the
    installed plugins use, or the wallpaper plugin will not load."""

    def setUp(self):
        self.srcs = shader_sources()

    def test_shaders_exist(self):
        self.assertIn("ink", self.srcs)
        self.assertIn("ink-melancholy", self.srcs)

    def test_version_440(self):
        for name, src in self.srcs.items():
            self.assertRegex(src, r"(?m)^#version\s+440\s*$", name)

    def test_uniform_block_layout(self):
        # The 80-byte UBO: qt_Matrix(64) @0, qt_Opacity @64, time @68,
        # resolution @72. The layout must match the Plasma convention.
        for name, src in self.srcs.items():
            m = re.search(
                r"layout\s*\(\s*std140\s*,\s*binding\s*=\s*0\s*\)\s*"
                r"uniform\s+buf\s*\{(.*?)\}\s*ubuf\s*;",
                src, re.S)
            self.assertIsNotNone(m, f"{name}: missing 'buf' UBO block")
            members = [line.strip() for line in m.group(1).splitlines()
                       if line.strip()]
            self.assertEqual(members, [
                "mat4 qt_Matrix;", "float qt_Opacity;",
                "float time;", "vec2 resolution;",
            ], f"{name}: UBO layout mismatch")

    def test_uses_plasma_uniforms(self):
        for name, src in self.srcs.items():
            self.assertIn("ubuf.time", src, name)
            self.assertIn("ubuf.resolution", src, name)
            self.assertIn("ubuf.qt_Opacity", src, name)
            self.assertIn("qt_TexCoord0", src, name)

    def test_no_loops(self):
        # Cheap-by-design constraint: no for/while loops in fragment stage.
        for name, src in self.srcs.items():
            self.assertNotRegex(src, r"\bfor\s*\(", f"{name}: has a for loop")
            self.assertNotRegex(src, r"\bwhile\s*\(", f"{name}: has a while loop")

    def test_main_exists(self):
        for name, src in self.srcs.items():
            self.assertRegex(src, r"void\s+main\s*\(", name)


class TestTranspiler(unittest.TestCase):
    """The ESSL transpilation used by the headless/web renderer."""

    def test_strips_version_and_ubo(self):
        src = shader_sources()["ink"].encode()
        out = render.transpile_es(src).decode()
        self.assertNotIn("#version 440", out)
        self.assertTrue(out.startswith("#version 310 es"))
        self.assertNotIn("ubuf.", out)
        self.assertIn("uniform float u_time", out)
        self.assertIn("uniform vec2 u_resolution", out)
        self.assertIn("u_time", out)
        self.assertIn("u_resolution", out)

    def test_unhandled_member_raises(self):
        bad = ("#version 440\n"
               "layout(std140, binding = 0) uniform buf {"
               " mat4 qt_Matrix; float qt_Opacity; float time; "
               "vec2 resolution; float extra; } ubuf;\n"
               "void main() { fragColor = vec4(ubuf.extra); }")
        with self.assertRaises(ValueError):
            render.transpile_es(bad.encode())


class TestQmlTemplate(unittest.TestCase):
    def test_frame_synced_animation(self):
        qml = open(TEMPLATE).read()
        self.assertIn("FrameAnimation", qml)
        self.assertNotRegex(qml, r"\bTimer\s*\{", "legacy Timer clock present")
        # time must come from the frame clock
        self.assertRegex(qml, r"frameClock\.elapsedTime\s*\*\s*animationRate")

    def test_placeholders_are_known(self):
        qml = open(TEMPLATE).read()
        unknown = re.findall(r"@[A-Z_]+@", qml)
        self.assertEqual(sorted(unknown),
                         sorted(["@SHADER@", "@RENDER_SCALE@"]))

    def test_ink_variant_scale(self):
        # The ink family must render at reduced scale on large displays.
        self.assertRegex(
            open(TEMPLATE).read(),
            r"layer\.enabled:\s*renderScale\s*<\s*0\.999")


class TestTimerQmlTemplate(unittest.TestCase):
    """The very slow variants repaint on a Timer, not the frame loop."""

    def test_timer_clock(self):
        qml = open(TIMER_TEMPLATE).read()
        self.assertRegex(qml, r"Timer\s*\{")
        self.assertRegex(qml, r"interval:\s*500")
        self.assertRegex(qml, r"time:\s*tick\s*\*\s*0\.5")
        self.assertNotIn("FrameAnimation", qml)

    def test_placeholders_are_known(self):
        qml = open(TIMER_TEMPLATE).read()
        unknown = re.findall(r"@[A-Z_]+@", qml)
        self.assertEqual(sorted(unknown),
                         sorted(["@SHADER@", "@RENDER_SCALE@"]))

    def test_build_script_selects_template(self):
        script = open(os.path.join(ROOT, "scripts", "build-packages.sh")).read()
        self.assertIn("main-timer.qml.in", script)
        self.assertRegex(
            script,
            r"linea\|topo-melancholy\)\s*qml_tmpl=\"main-timer\.qml\.in\"")


if __name__ == "__main__":
    unittest.main()
