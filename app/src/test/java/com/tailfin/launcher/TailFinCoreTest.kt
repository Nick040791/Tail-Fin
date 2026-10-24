package com.tailfin.launcher

import com.tailfin.launcher.ecosystem.NativeEcosystemManager
import com.tailfin.launcher.memory.MemoryOptimizer
import com.tailfin.launcher.memory.MemorySnapshot
import com.tailfin.launcher.notifications.DistractionFilterService
import com.tailfin.launcher.security.EnvEntry
import com.tailfin.launcher.security.EnvVaultRepository
import com.tailfin.launcher.security.LiteSecurityScanner
import com.tailfin.launcher.security.SecurityRiskLevel
import com.tailfin.launcher.terminal.AnsiArrowDirection
import com.tailfin.launcher.terminal.MobileTerminalKeyEncoder
import com.tailfin.launcher.terminal.TmuxQuickChord
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
    fun mobileTerminalKeyEncoderHandlesCtrlAltAndTmuxChords() {
        // Ctrl+C -> \u0003
        assertEquals("\u0003", MobileTerminalKeyEncoder.applyModifiers("c", ctrlActive = true, altActive = false))
        // Ctrl+D -> \u0004
        assertEquals("\u0004", MobileTerminalKeyEncoder.applyModifiers("d", ctrlActive = true, altActive = false))
        // Alt+x -> \u001Bx
        assertEquals("\u001Bx", MobileTerminalKeyEncoder.applyModifiers("x", ctrlActive = false, altActive = true))
        // Tmux chords start with Ctrl+B (\u0002)
        assertEquals("\u0002d", TmuxQuickChord.DETACH.sequence)
        assertEquals("\u0002c", TmuxQuickChord.CREATE.sequence)
        assertEquals("\u0002n", TmuxQuickChord.NEXT.sequence)
        assertEquals("\u0002p", TmuxQuickChord.PREV.sequence)
        // ANSI arrows
        assertEquals("\u001B[A", AnsiArrowDirection.UP.sequence)
        assertEquals("\u001B[B", AnsiArrowDirection.DOWN.sequence)
        assertEquals("\u001B[C", AnsiArrowDirection.RIGHT.sequence)
        assertEquals("\u001B[D", AnsiArrowDirection.LEFT.sequence)
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
        assertTrue(appIds.containsAll(setOf("tailscale", "orca", "chromium", "dicio", "fdroid", "shizuku", "taskmanager", "k9mail")))
        assertTrue(MemoryOptimizer.isProtectedPackage("com.tailfin.launcher"))
        assertTrue(MemoryOptimizer.isProtectedPackage("com.tailscale.ipn"))
        assertTrue(MemoryOptimizer.isProtectedPackage("com.stablyai.orca"))
        assertTrue(MemoryOptimizer.isProtectedPackage("moe.shizuku.privileged.api"))
        assertTrue(MemoryOptimizer.isProtectedPackage("org.stypox.dicio"))

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
