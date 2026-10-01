package com.axiom.glswall

import android.app.WallpaperManager
import android.content.ComponentName
import android.content.Context
import android.os.Bundle

/**
 * The wallpaper catalog. One WallpaperService + one settings activity per
 * variant (classic pattern, works on every Android version). On Android 16+
 * this could collapse into a single service using WallpaperDescription/
 * WallpaperInstance for per-instance content; the per-variant services stay
 * as the portable baseline.
 */
object WallRegistry {

    const val CMD_SET_MODE = "set-mode"
    const val EXTRA_MODE = "mode"
    const val MODE_LIVE = "live"
    const val MODE_STATIC = "static"

    /** Default animation rate — matches Plasma's animationRate and the web preview. */
    const val ANIMATION_RATE = 2.0f

    /**
     * Frame cap for the ANIM target. The display may run at 60/120 Hz; the
     * shaders are slow ambient motion, so 30 fps looks identical at half
     * (or a quarter) of the GPU work.
     */
    const val FPS_CAP = 30

    data class Wall(
        val id: String,
        val service: Class<*>,
    )

    val ALL: List<Wall> = listOf(
        Wall("ink", InkWallpaperService::class.java),
        Wall("ink-melancholy", InkMelancholyWallpaperService::class.java),
        Wall("caustics", CausticsWallpaperService::class.java),
    )

    fun byId(id: String): Wall = ALL.first { it.id == id }

    /** Push a live mode change into the currently-set wallpaper of this variant. */
    fun sendMode(ctx: Context, id: String, mode: String) {
        val wm = ctx.getSystemService(Context.WALLPAPER_SERVICE) as WallpaperManager
        wm.sendWallpaperCommand(
            ComponentName(ctx, byId(id).service.java),
            CMD_SET_MODE, 0, 0, 0,
            Bundle().apply { putString(EXTRA_MODE, mode) },
            false,
        )
    }
}
