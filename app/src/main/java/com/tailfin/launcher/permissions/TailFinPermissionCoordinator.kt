package com.tailfin.launcher.permissions

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.content.ContextCompat

object TailFinPermissionCoordinator {

    private const val PREFS_NAME = "tailfin_permissions_prefs"
    private const val KEY_FIRST_LAUNCH_COMPLETED = "first_launch_permissions_requested"

    const val PERM_READ_ENV_VAULT = "com.tailfin.permission.READ_ENV_VAULT"

    fun requiredRuntimePermissions(): List<String> = buildList {
        add(Manifest.permission.READ_CALENDAR)
        add(Manifest.permission.READ_CONTACTS)
        add(PERM_READ_ENV_VAULT)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            add(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    fun getMissingRuntimePermissions(context: Context): Array<String> {
        return requiredRuntimePermissions()
            .filter { perm ->
                ContextCompat.checkSelfPermission(context, perm) != PackageManager.PERMISSION_GRANTED
            }
            .toTypedArray()
    }

    fun isFirstLaunchPermissionPending(context: Context): Boolean {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        return !prefs.getBoolean(KEY_FIRST_LAUNCH_COMPLETED, false)
    }

    fun markFirstLaunchPermissionsRequested(context: Context) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putBoolean(KEY_FIRST_LAUNCH_COMPLETED, true)
            .apply()
    }
}
