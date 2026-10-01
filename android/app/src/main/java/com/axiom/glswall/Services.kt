package com.axiom.glswall

import android.service.wallpaper.WallpaperService

/** Base wallpaper service: one GLSL variant per concrete subclass. */
abstract class ShaderWallpaperService : WallpaperService() {
    abstract val variant: String

    override fun onCreateEngine(): WallpaperService.Engine = GlEngine(this, variant)
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
