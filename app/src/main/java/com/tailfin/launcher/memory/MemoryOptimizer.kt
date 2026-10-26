package com.tailfin.launcher.memory

import android.app.ActivityManager
import android.content.Context
import android.content.pm.PackageManager

data class MemorySnapshot(
    val availBytes: Long,
    val totalBytes: Long,
    val lowMemory: Boolean,
) {
    val usedBytes: Long get() = (totalBytes - availBytes).coerceAtLeast(0L)
    val availMb: Long get() = availBytes / (1024L * 1024L)
    val totalMb: Long get() = totalBytes / (1024L * 1024L)
    val usedMb: Long get() = usedBytes / (1024L * 1024L)
    val availRatio: Double get() = if (totalBytes > 0) availBytes.toDouble() / totalBytes.toDouble() else 1.0
    val usedPercent: Int get() = ((1.0 - availRatio) * 100.0).toInt().coerceIn(0, 100)
}

object MemoryOptimizer {

    val PROTECTED_PACKAGES = setOf(
        "com.tailfin.launcher",
        "com.galaxyrio.gracelauncher",
        "com.tailscale.ipn",
        "com.stablyai.orca",
        "com.stably.orca.mobile",
        "com.nicholas.fin",
        "com.scariflabs.horus",
        "net.thunderbird.android.beta",
        "net.thunderbird.android",
        "com.fsck.k9",
    )

    fun isProtectedPackage(packageName: String): Boolean =
        packageName in PROTECTED_PACKAGES

    fun getMemorySnapshot(context: Context): MemorySnapshot {
        val am = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        val memInfo = ActivityManager.MemoryInfo()
        am.getMemoryInfo(memInfo)
        return MemorySnapshot(
            availBytes = memInfo.availMem,
            totalBytes = memInfo.totalMem,
            lowMemory = memInfo.lowMemory,
        )
    }

    fun optimizeIfNeeded(context: Context, force: Boolean = false): Long {
        val am = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        val memInfo = ActivityManager.MemoryInfo()
        am.getMemoryInfo(memInfo)

        val availRatio = if (memInfo.totalMem > 0) {
            memInfo.availMem.toDouble() / memInfo.totalMem.toDouble()
        } else 1.0

        if (!force && !memInfo.lowMemory && availRatio > 0.22) {
            return 0L
        }

        val beforeAvail = memInfo.availMem
        @Suppress("DEPRECATION")
        val installedApps = context.packageManager.getInstalledApplications(PackageManager.GET_META_DATA)

        for (app in installedApps) {
            if (app.packageName !in PROTECTED_PACKAGES) {
                runCatching { am.killBackgroundProcesses(app.packageName) }
            }
        }

        System.gc()
        am.getMemoryInfo(memInfo)
        return (memInfo.availMem - beforeAvail).coerceAtLeast(0L)
    }
}
