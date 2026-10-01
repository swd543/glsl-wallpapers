#!/usr/bin/env python3
"""Generate animated GIF previews of every shader into previews/gifs/.

Stateless variants (shaders/*.frag) sample the shader at 480x270 over 84
frames of animation time; feedback variants (shaders/feedback/
<name>-ca.frag + <name>-comp.frag) run one cellular-automaton generation
per frame over the same 84 frames. Uses the same headless Mesa/EGL renderer
as the web preview, so the motion matches what Plasma / the web preview
show (web RATE 2.0 => shader-internal time advances 2.0x; frames step
0.3s of ubuf time, i.e. 25.2s of animation).

Run:  python3 scripts/make-gifs.py
"""
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import render  # noqa: E402
import feedback  # noqa: E402
from PIL import Image  # noqa: E402

W, H = 480, 270
FRAMES = 84
STEP = 0.3  # ubuf time per frame (shader-internal t = ubuf * 0.5)
DURATION_MS = 90  # playback speed per GIF frame


def save_gif(frames, out_path, name):
    # Fixed palette covering the whole animation (sampled from a strip of
    # every 4th frame): keeps the animation temporally consistent and the
    # GIF small — important for the feedback variants, whose early frames
    # are much darker than the later ones.
    sub = frames[::4]
    strip = Image.new("RGB", (W, len(sub) * H))
    for i, f in enumerate(sub):
        strip.paste(f, (0, i * H))
    palette = strip.convert("P", palette=Image.ADAPTIVE, colors=256)
    pframes = [f.convert("P", palette=palette) for f in frames]
    pframes[0].save(
        out_path, format="GIF", save_all=True, append_images=pframes[1:],
        duration=DURATION_MS, loop=0, optimize=False)
    size_kb = os.path.getsize(out_path) // 1024
    print(f"GIF {name}: {FRAMES} frames -> {out_path} ({size_kb} KB)")


def make_gif(frag_path, out_path, ctx):
    name = os.path.basename(frag_path)[:-5]
    src = open(frag_path, "rb").read()
    frames = []
    for i in range(FRAMES):
        rgba = ctx.render(src, i * STEP, key=f"gif-{name}")
        frames.append(Image.frombytes("RGBA", (W, H), rgba).convert("RGB"))
    save_gif(frames, out_path, name)


def make_feedback_gif(name, out_path, ctx):
    st = feedback.FeedbackState(name, ctx, os.path.join(ROOT, "shaders"))
    # pre-warm so the captured window shows mature structure (the first
    # generations after seeding are mostly empty/dark), and the palette
    # is built from frames of uniform brightness
    prewarm = {"mnca": 100, "life": 60}.get(name, 0)
    for i in range(prewarm):
        st.step(W, H, reset=(i == 0))
    frames = []
    for i in range(FRAMES):
        rgba = st.step(W, H)
        frames.append(Image.frombytes("RGBA", (W, H), rgba).convert("RGB"))
    save_gif(frames, out_path, name)


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
    for fb_name in feedback.discover(os.path.join(ROOT, "shaders")):
        make_feedback_gif(
            fb_name, os.path.join(ROOT, "previews", "gifs",
                                  fb_name + ".gif"), ctx)


if __name__ == "__main__":
    main()
