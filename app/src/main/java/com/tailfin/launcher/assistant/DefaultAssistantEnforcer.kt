package com.tailfin.launcher.assistant

import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.provider.Settings
import com.tailfin.launcher.ecosystem.ApkProvisioner
import com.tailfin.launcher.ecosystem.NativeEcosystemManager

object DefaultAssistantEnforcer {

    private const val PREFS_NAME = "tailfin_assistant_prefs"
    private const val KEY_ASSISTANT_PROMPTED = "fin_assistant_prompted"

    fun isFinDefaultAssistant(context: Context): Boolean = runCatching {
        val current = Settings.Secure.getString(context.contentResolver, "assistant").orEmpty()
        current.startsWith(NativeEcosystemManager.PKG_FIN)
    }.getOrDefault(false)

    fun openAssistantSettings(context: Context) {
        val voiceIntent = Intent(Settings.ACTION_VOICE_INPUT_SETTINGS).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        val defaultAppsIntent = Intent(Settings.ACTION_MANAGE_DEFAULT_APPS_SETTINGS).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        if (voiceIntent.resolveActivity(context.packageManager) != null) {
            runCatching { context.startActivity(voiceIntent) }
        } else {
            runCatching { context.startActivity(defaultAppsIntent) }
        }
    }

    fun verifyAndPrompt(context: Context, forcePrompt: Boolean = false) {
        if (isFinDefaultAssistant(context)) return

        val finInstalled = NativeEcosystemManager.isPackageInstalled(context, NativeEcosystemManager.PKG_FIN)
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        if (!forcePrompt && prefs.getBoolean(KEY_ASSISTANT_PROMPTED, false)) return

        val activity = context as? Activity ?: return
        if (activity.isFinishing || activity.isDestroyed) return

        prefs.edit().putBoolean(KEY_ASSISTANT_PROMPTED, true).apply()

        runCatching {
            val message = if (finInstalled) {
                "Set Fin as your default Android Digital Assistant in phone settings so home gestures and system assist shortcuts launch Fin directly."
            } else {
                "Install the bundled Fin Assistant app and set it as your default Android Digital Assistant in phone settings."
            }
            val positiveLabel = if (finInstalled) "Open Assistant Settings" else "Install Fin & Open Settings"

            AlertDialog.Builder(activity)
                .setTitle("Set Fin as Default Assistant")
                .setMessage(message)
                .setPositiveButton(positiveLabel) { _, _ ->
                    if (!finInstalled) {
                        ApkProvisioner.installBundledApk(context, "apks/fin-debug.apk", NativeEcosystemManager.PKG_FIN)
                    }
                    openAssistantSettings(context)
                }
                .setNegativeButton("Later", null)
                .show()
        }
    }
}
