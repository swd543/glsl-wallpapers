package com.axiom.glswall

import android.app.Activity
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.widget.LinearLayout
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.TextView

/**
 * Minimal per-variant settings: live vs static. No AndroidX — a plain
 * Activity with a programmatic UI, so the app has zero runtime dependencies.
 */
abstract class BaseSettingsActivity : Activity() {
    abstract val variant: String

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        title = getString(labelRes())

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(48, 64, 48, 64)
        }

        val note = TextView(this).apply {
            text = "Rendering stops when the screen is off or in Always-On Display, " +
                "and automatically when the device is in power-save mode or thermally " +
                "throttled. The choice below applies while the screen is on."
            textSize = 14f
            setPadding(0, 0, 0, 48)
        }

        val group = RadioGroup(this)
        val live = RadioButton(this).apply {
            text = getString(R.string.mode_live)
            id = View.generateViewId()
        }
        val stat = RadioButton(this).apply {
            text = getString(R.string.mode_static)
            id = View.generateViewId()
        }
        group.addView(live)
        group.addView(stat)
        group.check(
            if (WallSettings.mode(this, variant) == WallRegistry.MODE_STATIC) stat.id
            else live.id,
        )
        group.setOnCheckedChangeListener { _, id ->
            val mode = if (id == stat.id) WallRegistry.MODE_STATIC else WallRegistry.MODE_LIVE
            // The engine polls this preference ~1 Hz; no IPC needed.
            WallSettings.setMode(this, variant, mode)
        }

        root.addView(note)
        root.addView(group)
        setContentView(root)
    }

    /** Label resource for the corresponding wallpaper. */
    protected abstract fun labelRes(): Int
}

class InkSettingsActivity : BaseSettingsActivity() {
    override val variant = "ink"
    override fun labelRes() = R.string.wall_ink
}

class InkMelancholySettingsActivity : BaseSettingsActivity() {
    override val variant = "ink-melancholy"
    override fun labelRes() = R.string.wall_ink_melancholy
}

class CausticsSettingsActivity : BaseSettingsActivity() {
    override val variant = "caustics"
    override fun labelRes() = R.string.wall_caustics
}
