package com.axiom.glswall

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.display.DisplayManager
import android.opengl.EGL14
import android.opengl.EGLContext
import android.opengl.EGLDisplay
import android.opengl.EGLExt
import android.opengl.EGLSurface
import android.opengl.GLES20
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import android.util.Log
import android.view.Display
import android.view.SurfaceHolder
import android.service.wallpaper.WallpaperService
import java.nio.charset.Charset
import java.util.concurrent.Executor
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Base wallpaper service: one concrete subclass per GLSL variant.
 *
 * The engine is declared as an *inner* class of this service:
 * WallpaperService.Engine is a Java inner class, and Kotlin only accepts
 * the outer receiver for it from a containing class instance — you cannot
 * pass the WallpaperService as a constructor argument (that produces
 * "too many arguments") or call it without a receiver (that produces
 * "can only be called with a receiver of the containing class").
 */
abstract class ShaderWallpaperService : WallpaperService() {

    abstract val variant: String

    override fun onCreateEngine(): WallpaperService.Engine = GlEngine(variant)

    /**
     * Renders one transpiled ESSL 3.2 fragment shader
     * (assets/shaders/<variant>.glsl) directly onto the wallpaper window's
     * [SurfaceHolder] with a manual EGL context on a dedicated render thread —
     * no View, no GLSurfaceView; the wallpaper window's surface is the one
     * the framework hands the engine.
     *
     * Power model (the whole point of this app):
     *  - OFF    → render thread idles, zero GL work (not visible, or screen off).
     *  - STATIC → exactly one frame, then idle. Entered for AOD (display DOZE),
     *             power-save mode, thermal throttling, or the user's static mode.
     *             Note: targeting Android 16, the framework no longer holds the
     *             per-frame DRAW_WAKE_LOCK during DOZE (compat change
     *             DISABLE_DRAW_WAKE_LOCK_WALLPAPER), so AOD animation is a
     *             platform no-go anyway — one good frame is the correct design.
     *  - ANIM   → vsync'd, capped at [WallRegistry.FPS_CAP] fps by frame pacing.
     *
     * No wakelocks are ever held (Google Play's 2026 wake-lock quality
     * enforcement), no offset notifications (no parallax), no touch events.
     */
    inner class GlEngine(val variant: String) : WallpaperService.Engine() {

        enum class Target { OFF, STATIC, ANIM }

        private val service: WallpaperService = this@ShaderWallpaperService
        private var holder: SurfaceHolder? = null
        private var thread: RenderThread? = null
        private val visible = AtomicBoolean(false)

        @Volatile private var displayState = Display.STATE_ON
        @Volatile private var powerSave = false
        @Volatile private var thermalHot = false
        @Volatile private var userMode = WallRegistry.MODE_LIVE

        private val main = Handler(Looper.getMainLooper())
        private val pm = service.getSystemService(Context.POWER_SERVICE) as PowerManager
        private val dm = service.getSystemService(Context.DISPLAY_SERVICE) as DisplayManager

        private val powerSaveReceiver = object : BroadcastReceiver() {
            override fun onReceive(c: Context?, intent: Intent?) {
                powerSave = pm.isPowerSaveMode
            }
        }

        private val displayListener = object : DisplayManager.DisplayListener {
            override fun onDisplayAdded(displayId: Int) = Unit
            override fun onDisplayRemoved(displayId: Int) = Unit
            override fun onDisplayChanged(displayId: Int) {
                displayState = pm.displayState
            }
        }

        private val thermalListener = object : PowerManager.ThermalStatusListener {
            override fun onThermalStatusChanged(status: Int) {
                thermalHot = status >= PowerManager.THERMAL_STATUS_THROTTLING
            }
        }

        private val surfaceCallback = object : SurfaceHolder.Callback2 {
            override fun surfaceCreated(h: SurfaceHolder) = Unit
            override fun surfaceChanged(h: SurfaceHolder, format: Int, w: Int, h2: Int) = Unit
            override fun surfaceDestroyed(h: SurfaceHolder) = Unit

            // The system asks for a fresh frame (e.g. after it has frozen the
            // wallpaper onto a screenshot surface). Redraw one and idle.
            override fun surfaceRedrawNeeded(h: SurfaceHolder) {
                thread?.requestFrame()
            }
        }

        override fun onCreate(surfaceHolder: SurfaceHolder) {
            holder = surfaceHolder
            surfaceHolder.addCallback(surfaceCallback)
            // No parallax interest — skip the offset notification traffic.
            setOffsetNotificationsEnabled(false)

            service.registerReceiver(
                powerSaveReceiver,
                IntentFilter(PowerManager.ACTION_POWER_SAVE_MODE_CHANGED),
                Context.RECEIVER_NOT_EXPORTED,
            )
            dm.registerDisplayListener(displayListener, main)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                pm.addThermalStatusListener(Executor { main.post(it) }, thermalListener)
            }
            powerSave = pm.isPowerSaveMode
            displayState = pm.displayState
            userMode = WallSettings.mode(service, variant)

            thread = RenderThread(service).also { it.start() }
        }

        override fun onVisibilityChanged(visible: Boolean) {
            this.visible.set(visible)
        }

        override fun onDesiredSizeChanged(desiredWidth: Int, desiredHeight: Int) {
            // Always render at the actual surface size; nothing to do.
        }

        override fun onCommand(
            action: String?,
            x: Int,
            y: Int,
            z: Int,
            extras: Bundle?,
            resultRequested: Boolean,
        ): Bundle? {
            if (action == WallRegistry.CMD_SET_MODE) {
                val mode = extras?.getString(WallRegistry.EXTRA_MODE) ?: return null
                userMode = mode
                WallSettings.setMode(service, variant, mode)
                thread?.requestFrame()
            }
            return null
        }

        override fun onDestroy() {
            thread?.shutdown()
            thread?.join(500)
            thread = null
            holder?.removeCallback(surfaceCallback)
            holder = null
            service.unregisterReceiver(powerSaveReceiver)
            dm.unregisterDisplayListener(displayListener)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                pm.removeThermalStatusListener(thermalListener)
            }
        }

        /** Current power target; polled by the render thread every iteration. */
        fun target(): Target = when {
            !visible.get() || displayState == Display.STATE_OFF -> Target.OFF
            displayState == Display.STATE_DOZE ||
                displayState == Display.STATE_DOZE_SUSPEND -> Target.STATIC
            powerSave || thermalHot -> Target.STATIC
            userMode == WallRegistry.MODE_STATIC -> Target.STATIC
            else -> Target.ANIM
        }

        // -----------------------------------------------------------------
        // Render thread — owns the EGL display/context/surface.
        // -----------------------------------------------------------------
        private inner class RenderThread(private val ctx: Context) : Thread("wall-$variant") {

            private val lock = java.lang.Object()
            @Volatile private var stopRequested = false
            private var generation = 0L

            private var eglDisplay: EGLDisplay? = null
            private var eglContext: EGLContext? = null
            private var eglSurface: EGLSurface? = null
            private var config: IntArray? = null

            private var program = 0
            private var uTime = 0
            private var uRes = 0
            private var uOp = 0

            private val timeOriginNs = SystemClock.elapsedRealtimeNanos()
            private var lastDrawMs = 0L
            private var lastTarget: Target? = null
            private var staticArmed = false

            /** Wake the loop early (mode change, redraw request, shutdown). */
            fun requestFrame() {
                synchronized(lock) {
                    generation++
                    lock.notifyAll()
                }
            }

            fun shutdown() {
                synchronized(lock) {
                    stopRequested = true
                    generation++
                    lock.notifyAll()
                }
            }

            override fun run() {
                if (!initEgl()) return
                if (!loadShaders()) {
                    cleanupEgl()
                    return
                }
                while (!stopRequested) step()
                cleanupEgl()
            }

            private fun step() {
                val h = holder ?: return
                val wpSurface = h.surface
                if (wpSurface == null) {
                    destroyEglSurfaceIfAny()
                    staticArmed = true
                    waitIdle(100)
                    return
                }
                if (eglSurface == null) {
                    if (!createWindowSurface(wpSurface)) {
                        waitIdle(100)
                        return
                    }
                    staticArmed = true // new surface: make sure it gets a frame
                }

                val t = target()
                if (t != lastTarget) {
                    if (t == Target.STATIC) staticArmed = true
                    lastTarget = t
                }
                when (t) {
                    Target.OFF -> {
                        makeUncurrent()
                        waitIdle(250)
                    }
                    Target.STATIC -> {
                        if (staticArmed) {
                            drawFrame()
                            staticArmed = false
                        }
                        waitIdle(400)
                    }
                    Target.ANIM -> {
                        val minFrameMs = 1000L / WallRegistry.FPS_CAP
                        val wait = lastDrawMs + minFrameMs - SystemClock.elapsedRealtime()
                        if (wait > 0) waitIdle(wait) else drawFrame()
                    }
                }
            }

            private fun waitIdle(ms: Long) {
                val g0 = generation
                synchronized(lock) {
                    while (generation == g0 && !stopRequested) lock.wait(ms)
                }
            }

            private fun drawFrame() {
                val d = eglDisplay ?: return
                val s = eglSurface ?: return
                val c = eglContext ?: return
                if (!EGL14.eglMakeCurrent(d, s, s, c)) return
                val h = holder ?: return
                val w = h.surfaceWidth.coerceAtLeast(1)
                val hgt = h.surfaceHeight.coerceAtLeast(1)
                GLES20.glViewport(0, 0, w, hgt)
                GLES20.glUseProgram(program)
                val t = (SystemClock.elapsedRealtimeNanos() - timeOriginNs) / 1e9 *
                    WallRegistry.ANIMATION_RATE
                GLES20.glUniform1f(uTime, t)
                GLES20.glUniform2f(uRes, w.toFloat(), hgt.toFloat())
                GLES20.glUniform1f(uOp, 1f)
                GLES20.glDrawArrays(GLES20.GL_TRIANGLES, 0, 3)
                EGL14.eglSwapBuffers(d, s)
                lastDrawMs = SystemClock.elapsedRealtime()
            }

            // -- EGL lifecycle ------------------------------------------------

            private fun initEgl(): Boolean {
                val d = EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY)
                eglDisplay = d
                val major = IntArray(1)
                val minor = IntArray(1)
                if (!EGL14.eglInitialize(d, major, minor)) return fail("eglInitialize")
                if (!EGL14.eglBindAPI(EGL14.EGL_OPENGL_ES_API)) return fail("eglBindAPI")
                val attribs = intArrayOf(
                    EGL14.EGL_SURFACE_TYPE, EGL14.EGL_WINDOW_BIT,
                    EGL14.EGL_RENDERABLE_TYPE, EGLExt.EGL_OPENGL_ES3_BIT_KHR,
                    EGL14.EGL_RED_SIZE, 8,
                    EGL14.EGL_GREEN_SIZE, 8,
                    EGL14.EGL_BLUE_SIZE, 8,
                    EGL14.EGL_ALPHA_SIZE, 8,
                    EGL14.EGL_NONE,
                )
                val configs = arrayOf(IntArray(1))
                val num = IntArray(1)
                if (!EGL14.eglChooseConfig(d, attribs, configs, 1, num) || num[0] < 1) {
                    return fail("eglChooseConfig")
                }
                config = configs[0]
                val c = EGL14.eglCreateContext(
                    d, configs[0], EGL14.EGL_NO_CONTEXT,
                    intArrayOf(EGL14.EGL_CONTEXT_CLIENT_VERSION, 3), 0,
                )
                if (c == EGL14.EGL_NO_CONTEXT) return fail("eglCreateContext")
                eglContext = c
                EGL14.eglSwapInterval(d, 1) // vsync
                return true
            }

            private fun createWindowSurface(wpSurface: android.view.Surface): Boolean {
                val d = eglDisplay ?: return false
                val cfg = config ?: return false
                val s = EGL14.eglCreateWindowSurface(d, cfg, wpSurface, intArrayOf())
                if (s == EGL14.EGL_NO_SURFACE) return fail("eglCreateWindowSurface")
                eglSurface = s
                return true
            }

            private fun destroyEglSurfaceIfAny() {
                val s = eglSurface ?: return
                val d = eglDisplay ?: return
                makeUncurrent()
                EGL14.eglDestroySurface(d, s)
                eglSurface = null
            }

            private fun makeUncurrent() {
                val d = eglDisplay ?: return
                EGL14.eglMakeCurrent(d, EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_SURFACE,
                    EGL14.EGL_NO_CONTEXT)
            }

            private fun cleanupEgl() {
                val d = eglDisplay ?: return
                destroyEglSurfaceIfAny()
                eglContext?.let { EGL14.eglDestroyContext(d, it) }
                eglContext = null
                EGL14.eglTerminate(d)
                eglDisplay = null
            }

            private fun fail(what: String): Boolean {
                Log.e(TAG, "$what: EGL error 0x${
                    Integer.toHexString(EGL14.eglGetError())
                }")
                return false
            }

            // -- Shader setup ---------------------------------------------------

            private fun loadShaders(): Boolean {
                val vertSrc = asset("shaders/vert.glsl") ?: return false
                val fragSrc = asset("shaders/$variant.glsl") ?: return false
                val vs = compile(GLES20.GL_VERTEX_SHADER, vertSrc) ?: return false
                val fs = compile(GLES20.GL_FRAGMENT_SHADER, fragSrc) ?: return false
                val p = GLES20.glCreateProgram()
                GLES20.glAttachShader(p, vs)
                GLES20.glAttachShader(p, fs)
                GLES20.glLinkProgram(p)
                val ok = IntArray(1)
                GLES20.glGetProgramiv(p, GLES20.GL_LINK_STATUS, ok, 0)
                GLES20.glDeleteShader(vs)
                GLES20.glDeleteShader(fs)
                if (ok[0] == 0) {
                    Log.e(TAG, "link failed: ${GLES20.glGetProgramInfoLog(p)}")
                    GLES20.glDeleteProgram(p)
                    return false
                }
                program = p
                uTime = GLES20.glGetUniformLocation(p, "u_time")
                uRes = GLES20.glGetUniformLocation(p, "u_resolution")
                uOp = GLES20.glGetUniformLocation(p, "u_opacity")
                return true
            }

            private fun compile(type: Int, src: String): Int? {
                val s = GLES20.glCreateShader(type)
                GLES20.glShaderSource(s, src)
                GLES20.glCompileShader(s)
                val ok = IntArray(1)
                GLES20.glGetShaderiv(s, GLES20.GL_COMPILE_STATUS, ok, 0)
                if (ok[0] == 0) {
                    Log.e(TAG, "shader compile: ${GLES20.glGetShaderInfoLog(s)}")
                    GLES20.glDeleteShader(s)
                    return null
                }
                return s
            }

            private fun asset(path: String): String? = try {
                ctx.assets.open(path).use {
                    String(it.readBytes(), Charset.forName("UTF-8"))
                }
            } catch (e: Exception) {
                Log.e(TAG, "missing asset $path (run android/scripts/generate-assets.sh)")
                null
            }

            companion object {
                private const val TAG = "glswall"
            }
        }
    }
}

class InkWallpaperService : ShaderWallpaperService() {
    override val variant = "ink"
}

class InkMelancholyWallpaperService : ShaderWallpaperService() {
    override val variant = "ink-melancholy"
}

class CausticsWallpaperService : ShaderWallpaperService() {
    override val variant = "caustics"
}
