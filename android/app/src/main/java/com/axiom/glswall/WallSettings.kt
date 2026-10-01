package com.axiom.glswall

import android.content.Context

/** Per-variant user mode (live / static), persisted across reboots. */
object WallSettings {

    fun mode(ctx: Context, variant: String): String =
        ctx.getSharedPreferences("wall-$variant", Context.MODE_PRIVATE)
            .getString("mode", WallRegistry.MODE_LIVE)
            ?: WallRegistry.MODE_LIVE

    fun setMode(ctx: Context, variant: String, mode: String) {
        ctx.getSharedPreferences("wall-$variant", Context.MODE_PRIVATE)
            .edit()
            .putString("mode", mode)
            .apply()
    }
}
