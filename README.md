# GLSL Ink Wallpapers

Animated, texture-free GLSL 440 wallpapers for KDE Plasma **lock and login
screens**, rendered entirely on the integrated GPU.

Two variants, both in the domain-warped "ink in water" family:

| Variant | Install id | Look |
| --- | --- | --- |
| `ink` | `org.local.axiom.lockwall.ink` | Gold and pale-blue ink on deep green |
| `ink-melancholy` | `org.local.axiom.lockwall.ink-melancholy` | Dark rose and smoky violet ink on near-black plum |

## Preview

![ink-melancholy](previews/gifs/ink-melancholy.gif)
`ink-melancholy` — counter-rotating eddies, drifting "weather", randomized
droplets with random travel orientation

![ink](previews/gifs/ink.gif)
`ink`

Still frames: [ink](previews/ink.png) ·
[ink-melancholy](previews/ink-melancholy.png) ·
[contact sheet](previews/contact-sheet.png)

## How it works

Each variant is one `ShaderEffect` with an 80-byte standard Plasma UBO
(`qt_Matrix`, `qt_Opacity`, `time`, `resolution`). The fragment stage is
texture-free: hash value noise (4 hashes per sample), two domain warps, two
independent color fields, and a few micro-detail terms (`fwidth`-antialiased
iso-lines, flow-warped striations).

Non-repeating motion is driven entirely by cheap per-frame hashes — no
state, no loops:

* 8-second "weather" slots re-target eddy positions, strengths and drift
  direction with smoothstep-crossfades
* two counter-rotating eddies shear the structures past each other
* pseudo-random droplets: per-slot hash decides wait time, duration, **full
  360° travel orientation**, path arc and shape; each drop eases out of its
  speed and dissolves (fades + spreads) before leaving the frame; ~1 in 7
  slots is skipped so pauses vary

Animation is frame-synced: a `FrameAnimation` (no FPS cap) feeds
`ubuf.time = frameClock.elapsedTime * animationRate`.

**Cost note.** The ink family is the most expensive thing you can reasonably
run on a lock screen. It renders at **67% linear resolution** and lets the
compositor upscale — on a 3840×2160 display that is a 2573×1440 layer,
which keeps frame pacing smooth while the soft marbled look survives
upscaling. `renderScale` (per variant) and `animationRate` live in
`templates/main.qml.in` / `scripts/build-packages.sh`.

## Requirements

* KDE Plasma 5 or 6 (lock: `kscreenlocker`, login: `plasmalogin`)
* `qsb-qt6` to compile the shaders
  (Fedora: `sudo dnf install qt6-qtshadertools`)
* Python 3 + Pillow + a Mesa/EGL GPU — only for the preview tooling
  (web preview, GIFs, tests), **not** for the wallpapers themselves

## Building

```sh
scripts/build-packages.sh
```

compiles every `shaders/*.frag` into `shaders/*.frag.qsb` (via `qsb-qt6
--qt6`, the invocation Plasma's own pipeline uses) and assembles
installable plugin directories under `build/`:

```
build/org.local.axiom.lockwall.ink/
  contents/
    ui/
      main.qml            # ShaderEffect + FrameAnimation + renderScale
      ink.frag            # shader source (mirror, for reference)
      ink.frag.qsb        # compiled shader (what Plasma loads)
    metadata.json
```

Re-run this after any shader edit. `.qsb` files are build artifacts and
are not tracked in git — a fresh clone must run `scripts/build-packages.sh`
before installing. Never hand-edit `.qsb` files.

## Installing on a KDE system

### 1. Copy the plugin(s)

System-wide (needed for the **login screen**, which runs as the greeter
user and only sees system paths):

```sh
sudo cp -r build/org.local.axiom.lockwall.ink* /usr/share/plasma/wallpapers/
```

Per-user (lock screen and desktop only):

```sh
mkdir -p ~/.local/share/plasma/wallpapers
cp -r build/org.local.axiom.lockwall.ink* ~/.local/share/plasma/wallpapers/
```

### 2. Lock screen

**Plasma 6** (kscreenlocker 6.x) reads the greeter config from the
**`[Greeter]`** section of `~/.config/kscreenlockerrc`:

```ini
[Greeter]
WallpaperPlugin=org.local.axiom.lockwall.ink-melancholy
```

**Plasma 5** uses the `[kscreenlocker]` section instead:

```ini
[kscreenlocker]
WallpaperPlugin=org.local.axiom.lockwall.ink-melancholy
```

(Or pick the wallpaper in *System Settings → Screen Lock → Wallpaper*.)
A system-wide default may live in `/etc/xdg/kscreenlockerrc`; the user
file overrides it.

### 3. Login screen

`plasmalogin` reads `/etc/plasmalogin.conf`, greeter section
(`WallpaperPluginId`, not `WallpaperPlugin`):

```ini
[Greeter]
WallpaperPluginId=org.local.axiom.lockwall.ink-melancholy
```

Requires the **system-wide** copy from step 1.

### 4. Apply

* **Switch User / Login:** a new greeter process starts every time, so it
  picks up the new config automatically.
* **Lock screen:** `kscreenlocker_greet` caches the config for its whole
  lifetime. If it is already running, restart it once:

  ```sh
  kill "$(pgrep -f /usr/libexec/kscreenlocker_greet)"   # it respawns
  ```

### Uninstall

```sh
sudo rm -rf /usr/share/plasma/wallpapers/org.local.axiom.lockwall.ink*
# and restore the previous WallpaperPlugin / WallpaperPluginId values
# (remove the lines to fall back to the system default)
```

## Web preview

Serves every shader as live PNG frames on a phone-friendly page with GPU /
RAM stats. Runs its own headless Mesa/EGL renderer (surfaceless, AMD-only
ICD pinning), so it works without X.

```sh
python3 scripts/webserver.py --port 8090
# -> http://192.168.x.y:8090  (0.0.0.0 bind)
```

Endpoints: `/` (page), `/frame?variant=&res=WxH` (PNG), `/stats` (GPU busy
%, VRAM, fps, RAM), `/healthz`. Shader edits are picked up without a
restart (mtime-aware cache); restart after changing `RATE` in
`scripts/webserver.py`.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

* `tests/test_structure.py` — no GPU: Plasma UBO layout/convention checks
  (`#version 440`, 80-byte `buf` block, no loops), the ESSL transpiler, and
  the QML template (frame-synced clock, known placeholders).
* `tests/test_render.py` — GPU integration: renders every shader and checks
  frames are non-black, lock-screen-dark (no white-hot areas), animated
  over time, and within a frame-budget ceiling. Skipped when no
  EGL/Mesa GPU is available.
* `tests/test_webserver.py` — starts the server on a free port and checks
  `/healthz`, `/stats` (variant list, rate), index page, unknown-variant
  rejection, and a rendered `/frame` PNG. GPU-dependent checks skip when
  unavailable.

## Regenerating previews

```sh
python3 scripts/make-gifs.py          # previews/gifs/<variant>.gif
python3 scripts/render.py shaders/ink.frag out.png 12.0 1280 720
```

## Android

The same shaders ship as Android live wallpapers under `android/`.
Shaders are the single source of truth: `android/scripts/generate-assets.sh`
transpiles each `shaders/*.frag` to ESSL 3.2 (`#version 310 es`, flat
`u_time`/`u_resolution`/`u_opacity` uniforms) into the APK's assets, where
they compile on-device at first launch. The `.qsb`/Plasma build and the
Android asset build never diverge from the GLSL.

**Power model** (the app holds no wakelocks and never requests battery-
optimization exemption):

* **OFF** — render thread idles, zero GL work, when the wallpaper is not
  visible or the screen is off.
* **STATIC** — exactly one frame, then idle, for Always-On Display (display
  DOZE), power-save mode, thermal throttling, or the user's static choice.
  Targeting Android 16, the platform no longer allows AOD animation anyway
  (the `DRAW_WAKE_LOCK` compat change), so one good frame is the right design.
* **ANIM** — vsync'd and capped at 30 fps (ambient motion, 30 fps reads
  identically at half/quarter the GPU cost of 60/120 Hz).

Build (needs JDK 17 + an Android SDK with `platforms;android-36`):

```sh
android/scripts/generate-assets.sh
(cd android && gradle :app:assembleDebug)
```

GitHub Actions builds the debug APK on every relevant push (see
`.github/workflows/android.yml`).

## Notes

* All preview tooling (web server, GIFs, tests) uses the iGPU with a
  Mesa/EGL surfaceless context; pick whichever GPU you want via the normal
  environment variables if your machine has several.

## License

MIT — see [LICENSE](LICENSE).
