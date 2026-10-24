package com.tailfin.launcher.notifications

import android.app.Notification
import android.content.Context
import android.service.notification.StatusBarNotification
import androidx.core.content.edit

/**
 * TailFin Distraction-Free UI filter.
 * Suppresses non-essential notification badges and promotional/telemetry alerts while
 * preserving priority notifications from core FOSS tools (Tailscale, Orca, Dicio, K-9 Mail).
 */
object DistractionFilterService {

    private const val PREFS_NAME = "tailfin_distraction_filter"
    private const val KEY_FILTER_ENABLED = "distraction_filter_enabled"
    private const val KEY_SUPPRESS_BADGES = "suppress_non_essential_badges"

    val ESSENTIAL_PACKAGES: Set<String> = setOf(
        "com.tailfin.launcher",
        "com.tailscale.ipn",
        "com.stablyai.orca",
        "com.stably.orca.mobile",
        "org.stypox.dicio",
        "com.fsck.k9",
        "net.thunderbird.android",
        "moe.shizuku.privileged.api",
        "com.rk.taskmanager",
        "org.fdroid.fdroid",
        "com.android.dialer",
        "com.google.android.dialer",
        "com.android.messaging",
        "com.android.deskclock",
    )

    val BLOCKED_CATEGORIES: Set<String> = setOf(
        Notification.CATEGORY_PROMO,
        Notification.CATEGORY_RECOMMENDATION,
        Notification.CATEGORY_SOCIAL,
    )

    fun isFilterEnabled(context: Context): Boolean {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        return prefs.getBoolean(KEY_FILTER_ENABLED, false)
    }

    fun setFilterEnabled(context: Context, enabled: Boolean) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit {
            putBoolean(KEY_FILTER_ENABLED, enabled)
        }
    }

    fun isBadgeSuppressionEnabled(context: Context): Boolean {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        return prefs.getBoolean(KEY_SUPPRESS_BADGES, false)
    }

    fun setBadgeSuppressionEnabled(context: Context, enabled: Boolean) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit {
            putBoolean(KEY_SUPPRESS_BADGES, enabled)
        }
    }

    fun shouldAllowNotification(
        packageName: String,
        category: String?,
        isOngoing: Boolean,
        filterEnabled: Boolean,
    ): Boolean {
        if (!filterEnabled) return true
        if (packageName in ESSENTIAL_PACKAGES) return true
        if (category != null && category in BLOCKED_CATEGORIES) return false
        if (category == Notification.CATEGORY_ALARM || category == Notification.CATEGORY_CALL) return true
        if (isOngoing && packageName !in ESSENTIAL_PACKAGES) return false
        return true
    }

    fun shouldAllowStatusBarNotification(context: Context, sbn: StatusBarNotification): Boolean {
        val filterEnabled = isFilterEnabled(context)
        if (!filterEnabled) return true
        if (isBadgeSuppressionEnabled(context) && sbn.packageName !in ESSENTIAL_PACKAGES) {
            return false
        }
        return shouldAllowNotification(
            packageName = sbn.packageName,
            category = sbn.notification.category,
            isOngoing = sbn.isOngoing,
            filterEnabled = filterEnabled,
        )
    }
}
