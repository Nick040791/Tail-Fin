package com.tailfin.launcher

import android.Manifest
import com.galaxyrio.gracelauncher.data.icons.GraceButtonIcon
import com.tailfin.launcher.ecosystem.NativeEcosystemManager
import com.tailfin.launcher.memory.MemoryOptimizer
import com.tailfin.launcher.memory.MemorySnapshot
import com.tailfin.launcher.notifications.DistractionFilterService
import com.tailfin.launcher.permissions.TailFinPermissionCoordinator
import com.tailfin.launcher.security.EnvEntry
import com.tailfin.launcher.security.EnvVaultRepository
import com.tailfin.launcher.security.LiteSecurityScanner
import com.tailfin.launcher.security.SecurityRiskLevel
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class TailFinCoreTest {

    @Test
    fun envVaultParsesAndFormatsKeyValuesCorrectly() {
        val sample = """
            # Comment line
            SSH_HOST="100.101.102.103"
            SSH_USER=mrnicholas
            SSH_PORT="2222"
            ORCA_API_KEY='secret-orca-token'
        """.trimIndent()

        val entries = EnvVaultRepository.parseEnvText(sample)
        assertEquals(4, entries.size)
        assertEquals(EnvEntry("SSH_HOST", "100.101.102.103"), entries[0])
        assertEquals(EnvEntry("SSH_USER", "mrnicholas"), entries[1])
        assertEquals(EnvEntry("SSH_PORT", "2222"), entries[2])
        assertEquals(EnvEntry("ORCA_API_KEY", "secret-orca-token"), entries[3])

        val formatted = EnvVaultRepository.formatEnvEntries(entries)
        val reparsed = EnvVaultRepository.parseEnvText(formatted)
        assertEquals(entries, reparsed)
    }

    @Test
    fun liteSecurityScannerFlagsTelemetryAndHighRiskPermissions() {
        // 1. Known FOSS package is never flagged
        val fossFinding = LiteSecurityScanner.evaluatePackageRisk(
            packageName = "com.tailscale.ipn",
            appLabel = "Tailscale",
            requestedPermissions = listOf("android.permission.INTERNET"),
            installerPackage = null,
        )
        assertNull(fossFinding)

        // 2. Non-FOSS app with telemetry combo is flagged HIGH
        val telemetryFinding = LiteSecurityScanner.evaluatePackageRisk(
            packageName = "com.bloated.trackerapp",
            appLabel = "TrackerApp",
            requestedPermissions = listOf(
                "android.permission.INTERNET",
                "android.permission.ACCESS_FINE_LOCATION",
                "android.permission.READ_PHONE_STATE",
            ),
            installerPackage = "com.android.vending",
        )
        assertNotNull(telemetryFinding)
        assertEquals(SecurityRiskLevel.HIGH, telemetryFinding!!.riskLevel)
        assertTrue(telemetryFinding.hasTelemetryCombo)
        assertFalse(telemetryFinding.trustedInstaller)

        // 3. Trusted F-Droid app with no risky permissions is clean
        val cleanFdroid = LiteSecurityScanner.evaluatePackageRisk(
            packageName = "org.example.cleanfoss",
            appLabel = "CleanFOSS",
            requestedPermissions = listOf("android.permission.VIBRATE"),
            installerPackage = "org.fdroid.fdroid",
        )
        assertNull(cleanFdroid)
    }

    @Test
    fun searchButtonDefaultIconAndPermissionsCoordinatorAreConfigured() {
        assertEquals(R.drawable.ms_search, GraceButtonIcon.Suggestion.Default.drawable)
        val perms = TailFinPermissionCoordinator.requiredRuntimePermissions()
        assertTrue(perms.contains(Manifest.permission.READ_CALENDAR))
        assertTrue(perms.contains(Manifest.permission.READ_CONTACTS))
        assertTrue(perms.contains(TailFinPermissionCoordinator.PERM_READ_ENV_VAULT))
    }

    @Test
    fun distractionFilterProtectsEssentialPackagesAndBlocksPromo() {
        assertTrue(
            DistractionFilterService.shouldAllowNotification(
                packageName = "com.tailscale.ipn",
                category = "promo",
                isOngoing = true,
                filterEnabled = true,
            )
        )
        assertTrue(
            DistractionFilterService.shouldAllowNotification(
                packageName = "com.nicholas.fin",
                category = "promo",
                isOngoing = false,
                filterEnabled = true,
            )
        )
        assertFalse(
            DistractionFilterService.shouldAllowNotification(
                packageName = "com.random.shopping",
                category = "promo",
                isOngoing = false,
                filterEnabled = true,
            )
        )
        assertFalse(
            DistractionFilterService.shouldAllowNotification(
                packageName = "com.random.bloat",
                category = null,
                isOngoing = true,
                filterEnabled = true,
            )
        )
    }

    @Test
    fun nativeEcosystemAndMemoryOptimizerProtectCoreFossApps() {
        val appIds = NativeEcosystemManager.CORE_ECOSYSTEM_APPS.map { it.id }.toSet()
        assertTrue(appIds.containsAll(setOf("tailscale", "orca", "fin", "horus", "chromium", "fdroid", "shizuku", "taskmanager", "k9mail")))
        assertFalse(appIds.contains("dicio"))

        val finSpec = NativeEcosystemManager.CORE_ECOSYSTEM_APPS.first { it.id == "fin" }
        assertEquals("com.nicholas.fin", finSpec.primaryPackageName)
        assertEquals("fin-debug.apk", finSpec.bundledAssetName)

        val horusSpec = NativeEcosystemManager.CORE_ECOSYSTEM_APPS.first { it.id == "horus" }
        assertEquals("com.scariflabs.horus", horusSpec.primaryPackageName)
        assertEquals("horus-1.0.4.apk", horusSpec.bundledAssetName)

        assertTrue(MemoryOptimizer.isProtectedPackage("com.tailfin.launcher"))
        assertTrue(MemoryOptimizer.isProtectedPackage("com.tailscale.ipn"))
        assertTrue(MemoryOptimizer.isProtectedPackage("com.stablyai.orca"))
        assertTrue(MemoryOptimizer.isProtectedPackage("moe.shizuku.privileged.api"))
        assertTrue(MemoryOptimizer.isProtectedPackage("com.nicholas.fin"))
        assertTrue(MemoryOptimizer.isProtectedPackage("com.scariflabs.horus"))

        val snapshot = MemorySnapshot(
            availBytes = 1024L * 1024L * 1024L,
            totalBytes = 4096L * 1024L * 1024L,
            lowMemory = false,
            shizukuAvailable = true,
        )
        assertEquals(75, snapshot.usedPercent)
        assertEquals(1024L, snapshot.availMb)
        assertEquals(4096L, snapshot.totalMb)
    }
}
