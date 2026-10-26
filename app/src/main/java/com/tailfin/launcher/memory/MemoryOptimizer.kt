package com.tailfin.launcher.memory

import android.app.ActivityManager
import android.content.Context
import android.content.pm.PackageManager
import rikka.shizuku.Shizuku

data class MemorySnapshot(
    val availBytes: Long,
    val totalBytes: Long,
    val lowMemory: Boolean,
    val shizukuAvailable: Boolean,
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
        "moe.shizuku.privileged.api",
        "com.nicholas.fin",
        "com.scariflabs.horus",
    )

    fun isProtectedPackage(packageName: String): Boolean =
        packageName in PROTECTED_PACKAGES

    fun isShizukuReady(): Boolean = runCatching {
        Shizuku.pingBinder() && Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED
    }.getOrDefault(false)

    fun getMemorySnapshot(context: Context): MemorySnapshot {
        val am = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        val memInfo = ActivityManager.MemoryInfo()
        am.getMemoryInfo(memInfo)
        return MemorySnapshot(
            availBytes = memInfo.availMem,
            totalBytes = memInfo.totalMem,
            lowMemory = memInfo.lowMemory,
            shizukuAvailable = isShizukuReady(),
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

        if (force && isShizukuReady()) {
            trimCachesViaShizuku()
        }

        System.gc()
        am.getMemoryInfo(memInfo)
        return (memInfo.availMem - beforeAvail).coerceAtLeast(0L)
    }

    private fun trimCachesViaShizuku() {
        runCatching {
            // Use Shizuku privileged binder if available to trim background cached processes
            val method = Shizuku::class.java.getDeclaredMethod(
                "newProcess",
                Array<String>::class.java,
                Array<String>::class.java,
                String::class.java,
            )
            method.isAccessible = true
            val process = method.invoke(null, arrayOf("am", "kill-all"), null, null) as? Process
            process?.waitFor()
        }
    }
}
