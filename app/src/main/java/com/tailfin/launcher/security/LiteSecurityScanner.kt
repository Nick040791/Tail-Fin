package com.tailfin.launcher.security

import android.content.Context
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.os.Build

enum class SecurityRiskLevel {
    LOW,
    MEDIUM,
    HIGH,
}

data class PackageSecurityFinding(
    val packageName: String,
    val appLabel: String,
    val riskLevel: SecurityRiskLevel,
    val highRiskPermissions: List<String>,
    val hasTelemetryCombo: Boolean,
    val installerPackage: String?,
    val trustedInstaller: Boolean,
)

data class SecurityAuditReport(
    val scannedPackagesCount: Int,
    val flaggedPackages: List<PackageSecurityFinding>,
    val highRiskCount: Int,
    val telemetryComboCount: Int,
    val untrustedInstallerCount: Int,
)

object LiteSecurityScanner {

    val HIGH_RISK_PERMISSIONS = setOf(
        "android.permission.SYSTEM_ALERT_WINDOW",
        "android.permission.BIND_ACCESSIBILITY_SERVICE",
        "android.permission.READ_LOGS",
        "android.permission.REQUEST_INSTALL_PACKAGES",
    )

    val TELEMETRY_COMBO_PERMISSIONS = setOf(
        "android.permission.INTERNET",
        "android.permission.ACCESS_FINE_LOCATION",
        "android.permission.READ_PHONE_STATE",
    )

    val TRUSTED_INSTALLERS = setOf(
        "org.fdroid.fdroid",
        "com.tailfin.launcher",
        "com.galaxyrio.gracelauncher",
        "adb",
        "com.android.shell",
    )

    val KNOWN_FOSS_PACKAGES = setOf(
        "com.tailfin.launcher",
        "com.galaxyrio.gracelauncher",
        "com.tailscale.ipn",
        "com.stablyai.orca",
        "com.stably.orca.mobile",
        "com.nicholas.fin",
        "com.scariflabs.horus",
        "org.chromium.chrome",
        "org.fdroid.fdroid",
        "moe.shizuku.privileged.api",
        "com.rk.taskmanager",
        "com.fsck.k9",
        "net.thunderbird.android",
        "org.fossify.filemanager",
        "org.breezyweather",
    )

    fun evaluatePackageRisk(
        packageName: String,
        appLabel: String,
        requestedPermissions: Collection<String>,
        installerPackage: String?,
    ): PackageSecurityFinding? {
        if (packageName in KNOWN_FOSS_PACKAGES) return null

        val permSet = requestedPermissions.toSet()
        val matchedHighRisk = HIGH_RISK_PERMISSIONS.filter { it in permSet }
        val hasTelemetryCombo = TELEMETRY_COMBO_PERMISSIONS.all { it in permSet }
        val trustedInstaller = installerPackage != null && installerPackage in TRUSTED_INSTALLERS

        if (matchedHighRisk.isEmpty() && !hasTelemetryCombo && trustedInstaller) {
            return null
        }

        val riskLevel = when {
            hasTelemetryCombo || matchedHighRisk.size >= 2 -> SecurityRiskLevel.HIGH
            matchedHighRisk.isNotEmpty() -> SecurityRiskLevel.MEDIUM
            else -> SecurityRiskLevel.LOW
        }

        return PackageSecurityFinding(
            packageName = packageName,
            appLabel = appLabel,
            riskLevel = riskLevel,
            highRiskPermissions = matchedHighRisk,
            hasTelemetryCombo = hasTelemetryCombo,
            installerPackage = installerPackage,
            trustedInstaller = trustedInstaller,
        )
    }

    fun scanInstalledPackages(context: Context): SecurityAuditReport {
        val pm = context.packageManager
        @Suppress("DEPRECATION")
        val packages = pm.getInstalledPackages(PackageManager.GET_PERMISSIONS)
        val findings = mutableListOf<PackageSecurityFinding>()
        var thirdPartyCount = 0

        for (pkgInfo in packages) {
            val appInfo = pkgInfo.applicationInfo ?: continue
            val isSystem = (appInfo.flags and ApplicationInfo.FLAG_SYSTEM) != 0 &&
                (appInfo.flags and ApplicationInfo.FLAG_UPDATED_SYSTEM_APP) == 0
            if (isSystem) continue

            thirdPartyCount++
            val label = runCatching { pm.getApplicationLabel(appInfo).toString() }.getOrDefault(pkgInfo.packageName)
            val perms = pkgInfo.requestedPermissions?.toList().orEmpty()
            val installer = getInstallerPackageNameCompat(pm, pkgInfo.packageName)

            val finding = evaluatePackageRisk(
                packageName = pkgInfo.packageName,
                appLabel = label,
                requestedPermissions = perms,
                installerPackage = installer,
            )
            if (finding != null && (finding.highRiskPermissions.isNotEmpty() || finding.hasTelemetryCombo || !finding.trustedInstaller)) {
                findings.add(finding)
            }
        }

        val sorted = findings.sortedWith(
            compareByDescending<PackageSecurityFinding> { it.riskLevel.ordinal }
                .thenByDescending { it.hasTelemetryCombo }
                .thenByDescending { it.highRiskPermissions.size }
                .thenBy { it.appLabel.lowercase() }
        )

        return SecurityAuditReport(
            scannedPackagesCount = thirdPartyCount,
            flaggedPackages = sorted,
            highRiskCount = sorted.count { it.riskLevel == SecurityRiskLevel.HIGH },
            telemetryComboCount = sorted.count { it.hasTelemetryCombo },
            untrustedInstallerCount = sorted.count { !it.trustedInstaller },
        )
    }

    private fun getInstallerPackageNameCompat(pm: PackageManager, packageName: String): String? = runCatching {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            pm.getInstallSourceInfo(packageName).installingPackageName
        } else {
            @Suppress("DEPRECATION")
            pm.getInstallerPackageName(packageName)
        }
    }.getOrNull()
}
