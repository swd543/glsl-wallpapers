package com.axiom.glswall

import android.content.Context

/**
 * The wallpaper catalog. One WallpaperService + one settings activity per
 * variant (classic pattern, works on every Android version). On Android 16+
 * this could collapse into a single service using WallpaperDescription/
 * WallpaperInstance for per-instance content; the per-variant services stay
 * as the portable baseline.
 */
object WallRegistry {

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
}
