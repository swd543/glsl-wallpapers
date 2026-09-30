#!/usr/bin/env python3
"""Generate animated GIF previews of every shader into previews/gifs/.

Each GIF samples the shader at 480x270 over 28 frames of animation time.
Uses the same headless Mesa/EGL renderer as the web preview, so the motion
matches what Plasma shows (web RATE 2.0 => shader-internal time advances
2.0x; frames below step 0.3s of ubuf time, i.e. 8.4s of animation).

Run:  python3 scripts/make-gifs.py
"""
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import render  # noqa: E402
from PIL import Image  # noqa: E402

W, H = 480, 270
FRAMES = 28
STEP = 0.3  # ubuf time per frame (shader-internal t = ubuf * 0.5)
DURATION_MS = 90  # playback speed per GIF frame


def make_gif(frag_path, out_path, ctx):
    name = os.path.basename(frag_path)[:-5]
    src = open(frag_path, "rb").read()
    frames = []
    for i in range(FRAMES):
        rgba = ctx.render(src, i * STEP, key=f"gif-{name}")
        im = Image.frombytes("RGBA", (W, H), rgba).convert("RGB")
        frames.append(im)
    # Fixed palette taken from the first frame: keeps the animation
    # temporally consistent and keeps the GIF small.
    palette = frames[0].convert("P", palette=Image.ADAPTIVE, colors=256)
    pframes = [f.convert("P", palette=palette) for f in frames]
    pframes[0].save(
        out_path, format="GIF", save_all=True, append_images=pframes[1:],
        duration=DURATION_MS, loop=0, optimize=False)
    size_kb = os.path.getsize(out_path) // 1024
    print(f"GIF {name}: {FRAMES} frames -> {out_path} ({size_kb} KB)")


def main():
    frags = sorted(glob.glob(os.path.join(ROOT, "shaders", "*.frag")))
    if not frags:
        print("no shaders found", file=sys.stderr)
        sys.exit(1)
    os.makedirs(os.path.join(ROOT, "previews", "gifs"), exist_ok=True)
    ctx = render.RenderContext(W, H)
    print(f"GL: {ctx.gl_vendor} {ctx.gl_renderer} "
          f"({ctx.gl_version.split()[2]})")
    for frag in frags:
        name = os.path.basename(frag)[:-5]
        make_gif(frag, os.path.join(ROOT, "previews", "gifs", name + ".gif"),
                 ctx)


if __name__ == "__main__":
    main()
