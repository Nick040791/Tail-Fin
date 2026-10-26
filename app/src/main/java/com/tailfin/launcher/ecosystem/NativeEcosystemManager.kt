package com.tailfin.launcher.ecosystem

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import java.io.File
import java.net.Inet4Address
import java.net.NetworkInterface

data class EcosystemAppSpec(
    val id: String,
    val title: String,
    val roleDescription: String,
    val primaryPackageName: String,
    val alternatePackageNames: List<String> = emptyList(),
    val bundledAssetName: String? = null,
    val sourceRepo: String,
) {
    val allPackageNames: List<String>
        get() = listOf(primaryPackageName) + alternatePackageNames
}

data class TailscaleStatus(
    val installed: Boolean,
    val vpnActive: Boolean,
    val tailnetIp: String? = null,
)

object NativeEcosystemManager {

    const val PKG_TAILSCALE = "com.tailscale.ipn"
    const val PKG_ORCA = "com.stablyai.orca"
    const val PKG_ORCA_ACTUAL = "com.stably.orca.mobile"
    const val PKG_CHROMIUM = "org.chromium.chrome"
    const val PKG_FIN = "com.nicholas.fin"
    const val PKG_HORUS = "com.scariflabs.horus"
    const val PKG_FDROID = "org.fdroid.fdroid"
    const val PKG_SHIZUKU = "moe.shizuku.privileged.api"
    const val PKG_TASKMANAGER = "com.rk.taskmanager"
    const val PKG_K9MAIL = "com.fsck.k9"
    const val PKG_FOSSIFY_FILES = "org.fossify.filemanager"

    val CORE_ECOSYSTEM_APPS: List<EcosystemAppSpec> = listOf(
        EcosystemAppSpec(
            id = "tailscale",
            title = "Tailscale",
            roleDescription = "Mesh VPN status pill & MagicDNS host provider",
            primaryPackageName = PKG_TAILSCALE,
            bundledAssetName = "tailscale-android-universal-1.104.2.apk",
            sourceRepo = "tailscale/tailscale-android",
        ),
        EcosystemAppSpec(
            id = "orca",
            title = "Orca Mobile",
            roleDescription = "Primary pinned agent control center",
            primaryPackageName = PKG_ORCA,
            alternatePackageNames = listOf(PKG_ORCA_ACTUAL),
            bundledAssetName = "app-release.apk",
            sourceRepo = "stablyai/orca",
        ),
        EcosystemAppSpec(
            id = "fin",
            title = "Fin Assistant",
            roleDescription = "Default personal AI assistant (ACTION_ASSIST)",
            primaryPackageName = PKG_FIN,
            bundledAssetName = "fin-debug.apk",
            sourceRepo = "Nick040791/Tail-Fin",
        ),
        EcosystemAppSpec(
            id = "horus",
            title = "Horus Console",
            roleDescription = "Integrated terminal & console app",
            primaryPackageName = PKG_HORUS,
            bundledAssetName = "horus-1.0.4.apk",
            sourceRepo = "scariflabs/horus",
        ),
        EcosystemAppSpec(
            id = "chromium",
            title = "Chromium",
            roleDescription = "Default privacy browser & web search handler",
            primaryPackageName = PKG_CHROMIUM,
            alternatePackageNames = listOf("org.ungoogled.chromium", "com.brave.browser"),
            bundledAssetName = null,
            sourceRepo = "chromium/chromium",
        ),
        EcosystemAppSpec(
            id = "fdroid",
            title = "F-Droid",
            roleDescription = "Default open-source package manager",
            primaryPackageName = PKG_FDROID,
            bundledAssetName = "F-Droid.apk",
            sourceRepo = "f-droid.org",
        ),
        EcosystemAppSpec(
            id = "shizuku",
            title = "Shizuku",
            roleDescription = "Privileged ADB-level binder API for TailFin",
            primaryPackageName = PKG_SHIZUKU,
            bundledAssetName = "shizuku-v13.6.0.r1086.2650830c-release.apk",
            sourceRepo = "RikkaApps/Shizuku",
        ),
        EcosystemAppSpec(
            id = "taskmanager",
            title = "TaskManager",
            roleDescription = "Process monitor linked to TailFin RAM gauge",
            primaryPackageName = PKG_TASKMANAGER,
            bundledAssetName = "taskmanager-v1.5.2.apk",
            sourceRepo = "RohitKushvaha01/TaskManager",
        ),
        EcosystemAppSpec(
            id = "k9mail",
            title = "Thunderbird / K-9",
            roleDescription = "Default open-source email client",
            primaryPackageName = PKG_K9MAIL,
            alternatePackageNames = listOf("net.thunderbird.android"),
            bundledAssetName = "k9mail-24.0.apk",
            sourceRepo = "K9MAIL_24_0",
        ),
        EcosystemAppSpec(
            id = "fossify_files",
            title = "Fossify File Manager",
            roleDescription = "Open-source local file manager",
            primaryPackageName = PKG_FOSSIFY_FILES,
            bundledAssetName = "org.fossify.filemanager_13.apk",
            sourceRepo = "FossifyOrg/File-Manager",
        ),
    )

    fun resolvePackageNameFromApk(context: Context, assetApkPath: String): String? {
        return runCatching {
            val tempFile = File(context.cacheDir, "temp_inspect.apk")
            context.assets.open(assetApkPath).use { input ->
                tempFile.outputStream().use { output -> input.copyTo(output) }
            }
            @Suppress("DEPRECATION")
            val info = context.packageManager.getPackageArchiveInfo(tempFile.absolutePath, 0)
            tempFile.delete()
            info?.packageName
        }.getOrNull()
    }

    fun isPackageInstalled(context: Context, packageName: String): Boolean {
        return runCatching {
            @Suppress("DEPRECATION")
            context.packageManager.getPackageInfo(packageName, 0)
            true
        }.getOrDefault(false)
    }

    fun resolveInstalledPackage(context: Context, spec: EcosystemAppSpec): String? {
        for (pkg in spec.allPackageNames) {
            if (isPackageInstalled(context, pkg)) return pkg
        }
        return null
    }

    fun launchOrProvision(context: Context, packageName: String, bundledAssetName: String) {
        val spec = CORE_ECOSYSTEM_APPS.firstOrNull {
            it.primaryPackageName == packageName || packageName in it.alternatePackageNames
        }
        val candidates = spec?.allPackageNames ?: listOf(packageName)
        for (candidate in candidates) {
            val launchIntent = context.packageManager.getLaunchIntentForPackage(candidate)
            if (launchIntent != null) {
                launchIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                context.startActivity(launchIntent)
                return
            }
        }
        if (bundledAssetName.isNotBlank()) {
            val inspectedPkg = resolvePackageNameFromApk(context, "apks/$bundledAssetName")
            if (inspectedPkg != null && inspectedPkg !in candidates) {
                val inspectedLaunch = context.packageManager.getLaunchIntentForPackage(inspectedPkg)
                if (inspectedLaunch != null) {
                    inspectedLaunch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    context.startActivity(inspectedLaunch)
                    return
                }
            }
            ApkProvisioner.installBundledApk(context, "apks/$bundledAssetName", packageName)
        } else {
            ApkProvisioner.openInFDroidOrBrowser(context, packageName)
        }
    }

    fun launchSpec(context: Context, spec: EcosystemAppSpec) {
        launchOrProvision(context, spec.primaryPackageName, spec.bundledAssetName.orEmpty())
    }

    fun launchFinAssistant(context: Context): Boolean {
        val assistIntent = Intent(Intent.ACTION_ASSIST).apply {
            setPackage(PKG_FIN)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        if (assistIntent.resolveActivity(context.packageManager) != null) {
            return runCatching {
                context.startActivity(assistIntent)
                true
            }.getOrDefault(false)
        }
        val launchIntent = context.packageManager.getLaunchIntentForPackage(PKG_FIN)
        if (launchIntent != null) {
            return runCatching {
                launchIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                context.startActivity(launchIntent)
                true
            }.getOrDefault(false)
        }
        val finSpec = CORE_ECOSYSTEM_APPS.first { it.id == "fin" }
        finSpec.bundledAssetName?.let {
            ApkProvisioner.installBundledApk(context, "apks/$it", PKG_FIN)
            return true
        }
        return false
    }

    fun launchHorusConsole(context: Context) {
        val horusSpec = CORE_ECOSYSTEM_APPS.first { it.id == "horus" }
        launchSpec(context, horusSpec)
    }

    fun getTailscaleStatus(context: Context): TailscaleStatus {
        val installed = isPackageInstalled(context, PKG_TAILSCALE)
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
        val activeNetwork = cm?.activeNetwork
        val caps = if (activeNetwork != null) cm.getNetworkCapabilities(activeNetwork) else null
        val hasVpnTransport = caps?.hasTransport(NetworkCapabilities.TRANSPORT_VPN) == true
        val tailnetIp = findTailscaleCgnatIp()
        return TailscaleStatus(
            installed = installed,
            vpnActive = hasVpnTransport || tailnetIp != null,
            tailnetIp = tailnetIp,
        )
    }

    /**
     * Detects a Tailscale 100.64.0.0/10 CGNAT IPv4 address on local network interfaces.
     */
    internal fun findTailscaleCgnatIp(): String? = runCatching {
        val interfaces = NetworkInterface.getNetworkInterfaces() ?: return null
        for (nif in interfaces.iterator()) {
            if (!nif.isUp || nif.isLoopback) continue
            for (addr in nif.inetAddresses.iterator()) {
                if (addr is Inet4Address) {
                    val bytes = addr.address
                    val first = bytes[0].toInt() and 0xFF
                    val second = bytes[1].toInt() and 0xFF
                    if (first == 100 && second in 64..127) {
                        return addr.hostAddress
                    }
                }
            }
        }
        null
    }.getOrNull()
}
