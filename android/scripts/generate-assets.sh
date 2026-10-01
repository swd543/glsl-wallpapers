#!/usr/bin/env bash
# Regenerate the Android shader assets from the GLSL 440 sources.
#
#   shaders/*.frag          --transpile_es-->  android/app/src/main/assets/shaders/*.glsl
#   android/shaders/vert.glsl --copy-------->  android/app/src/main/assets/shaders/vert.glsl
#
# The transpiled ESSL 3.2 files are derived artifacts (like the .qsb files):
# generated here and gitignored. Run this after any shader edit and before
# building the APK (CI runs it automatically).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

python3 - "$ROOT" <<'PY'
import os
import re
import sys


def transpile_es(src: bytes) -> bytes:
    """GLSL 440 (Plasma ShaderEffect) -> ESSL 3.10. Math is untouched.

    Inline copy of scripts/render.py's transpile_es, kept dependency-free
    (stdlib only) so this script runs in CI without the preview tooling.
    """
    text = src.decode("utf-8")
    text = re.sub(r"^#version\s+4\d\d\s*", "", text, count=1, flags=re.M)
    text = re.sub(r"layout\s*\(\s*location\s*=\s*\d+\s*\)\s*in\s+", "in ", text)
    text = re.sub(r"layout\s*\(\s*location\s*=\s*\d+\s*\)\s*out\s+", "out ", text)
    text = text.replace("gl_FragData[0]", "fragColor")
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


root = sys.argv[1]
asset_dir = os.path.join(root, "android", "app", "src", "main", "assets", "shaders")
os.makedirs(asset_dir, exist_ok=True)

with open(os.path.join(root, "android", "shaders", "vert.glsl"), "rb") as f:
    vert = f.read()
with open(os.path.join(asset_dir, "vert.glsl"), "wb") as f:
    f.write(vert)
print("  vert.glsl  (copied)")

for name in sorted(os.listdir(os.path.join(root, "shaders"))):
    if not name.endswith(".frag"):
        continue
    variant = name[:-5]
    with open(os.path.join(root, "shaders", name), "rb") as f:
        src = f.read()
    es = transpile_es(src)
    with open(os.path.join(asset_dir, variant + ".glsl"), "wb") as f:
        f.write(es)
    print(f"  {variant}.glsl  ({len(es)} bytes)")
PY

echo "Android shader assets written to android/app/src/main/assets/shaders/"
