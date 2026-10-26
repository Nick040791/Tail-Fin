package com.tailfin.launcher.devmode

import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.provider.Settings

object DeveloperModeEnforcer {

    @Volatile
    private var promptedThisSession: Boolean = false

    fun isDeveloperModeActive(context: Context): Boolean {
        return runCatching {
            Settings.Global.getInt(
                context.contentResolver,
                Settings.Global.DEVELOPMENT_SETTINGS_ENABLED,
                0
            ) != 0
        }.getOrDefault(false)
    }

    fun verifyAndPrompt(context: Context, forcePrompt: Boolean = false) {
        if (isDeveloperModeActive(context)) {
            promptedThisSession = false
            return
        }
        if (!forcePrompt && promptedThisSession) return
        val activity = context as? Activity ?: return
        if (activity.isFinishing || activity.isDestroyed) return

        promptedThisSession = true
        runCatching {
            AlertDialog.Builder(activity)
                .setTitle("Developer Mode Required")
                .setMessage("TailFin requires Android Developer Mode for Horus console debugging and developer tools. Enable it now?")
                .setPositiveButton("Open Settings") { _, _ ->
                    openDeveloperSettings(context)
                }
                .setNegativeButton("Later", null)
                .show()
        }
    }

    fun openDeveloperSettings(context: Context) {
        val devIntent = Intent(Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK
        }
        val fallbackIntent = Intent(Settings.ACTION_DEVICE_INFO_SETTINGS).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK
        }
        if (devIntent.resolveActivity(context.packageManager) != null) {
            runCatching { context.startActivity(devIntent) }
        } else {
            runCatching { context.startActivity(fallbackIntent) }
        }
    }
}
