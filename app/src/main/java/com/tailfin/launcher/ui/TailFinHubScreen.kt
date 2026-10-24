package com.tailfin.launcher.ui

import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.galaxyrio.gracelauncher.ui.settings.SettingsHeading
import com.galaxyrio.gracelauncher.ui.settings.SettingsList
import com.galaxyrio.gracelauncher.ui.settings.SettingsScaffold
import com.galaxyrio.gracelauncher.ui.theme.TailFinAmbientRed
import com.galaxyrio.gracelauncher.ui.theme.TailFinMetallicSilver
import com.galaxyrio.gracelauncher.ui.theme.TailFinOrcaBorder
import com.galaxyrio.gracelauncher.ui.theme.TailFinOrcaGray
import com.galaxyrio.gracelauncher.ui.theme.TailFinOrcaSurface
import com.galaxyrio.gracelauncher.ui.theme.TailFinScaleTeal
import com.galaxyrio.gracelauncher.ui.theme.TailFinTextMuted
import com.galaxyrio.gracelauncher.ui.theme.TailFinTextPrimary
import com.tailfin.launcher.devmode.DeveloperModeEnforcer
import com.tailfin.launcher.ecosystem.NativeEcosystemManager
import com.tailfin.launcher.memory.MemoryOptimizer
import com.tailfin.launcher.notifications.DistractionFilterService
import com.tailfin.launcher.security.EnvVaultRepository
import com.tailfin.launcher.security.LiteSecurityScanner
import com.tailfin.launcher.security.SecurityAuditReport
import com.tailfin.launcher.security.SecurityRiskLevel
import com.tailfin.launcher.terminal.SshTerminalDrawer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun TailFinHomeStatusPillBar(
    onOpenSshTerminal: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    var refreshTick by remember { mutableIntStateOf(0) }
    val tailscale = remember(context, refreshTick) { NativeEcosystemManager.getTailscaleStatus(context) }
    val memSnapshot = remember(context, refreshTick) { MemoryOptimizer.getMemorySnapshot(context) }
    val scrollState = rememberScrollState()

    Row(
        modifier = modifier
            .fillMaxWidth()
            .horizontalScroll(scrollState)
            .padding(vertical = 6.dp)
            .testTag("tailfin_status_pill_bar"),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        // 1. Tailscale VPN Status Pill
        StatusPillChip(
            label = if (tailscale.vpnActive) {
                "Tailscale: ${tailscale.tailnetIp ?: "Mesh Up"}"
            } else {
                "Tailscale: Offline"
            },
            accentColor = if (tailscale.vpnActive) TailFinScaleTeal else TailFinOrcaBorder,
            tag = "pill_tailscale",
            onClick = {
                val spec = NativeEcosystemManager.CORE_ECOSYSTEM_APPS.first { it.id == "tailscale" }
                NativeEcosystemManager.launchSpec(context, spec)
            },
        )

        // 2. Orca Agent Control Center Pill
        StatusPillChip(
            label = "Orca Agent",
            accentColor = TailFinAmbientRed,
            tag = "pill_orca",
            onClick = {
                val spec = NativeEcosystemManager.CORE_ECOSYSTEM_APPS.first { it.id == "orca" }
                NativeEcosystemManager.launchSpec(context, spec)
            },
        )

        // 3. SSH Terminal Drawer Trigger
        StatusPillChip(
            label = "SSH Terminal",
            accentColor = TailFinScaleTeal,
            tag = "pill_ssh_terminal",
            onClick = onOpenSshTerminal,
        )

        // 4. Dicio Voice/Text Assistant Pill
        StatusPillChip(
            label = "Dicio Assist",
            accentColor = TailFinOrcaBorder,
            tag = "pill_dicio",
            onClick = { NativeEcosystemManager.launchDicioAssistant(context) },
        )

        // 5. RAM Gauge & Memory Sweep Pill
        StatusPillChip(
            label = "RAM ${memSnapshot.usedPercent}% (${memSnapshot.availMb}MB free)",
            accentColor = if (memSnapshot.lowMemory) TailFinAmbientRed else TailFinOrcaBorder,
            tag = "pill_ram_gauge",
            onClick = {
                val freedBytes = MemoryOptimizer.optimizeIfNeeded(context, force = true)
                val freedMb = freedBytes / (1024L * 1024L)
                refreshTick++
                Toast.makeText(
                    context,
                    "TailFin Memory Sweep complete (${freedMb}MB reclaimed)",
                    Toast.LENGTH_SHORT,
                ).show()
            },
        )
    }
}

@Composable
private fun StatusPillChip(
    label: String,
    accentColor: Color,
    tag: String,
    onClick: () -> Unit,
) {
    Box(
        modifier = Modifier
            .clip(CircleShape)
            .background(TailFinOrcaSurface.copy(alpha = 0.88f))
            .border(1.dp, accentColor, CircleShape)
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 6.dp)
            .testTag(tag),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = label,
            color = TailFinTextPrimary,
            fontSize = 12.sp,
            fontWeight = FontWeight.Medium,
        )
    }
}

@Composable
fun TailFinHubScreen(
    onBack: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var showSshTerminal by remember { mutableStateOf(false) }
    var refreshCount by remember { mutableIntStateOf(0) }

    val devModeActive = remember(context, refreshCount) { DeveloperModeEnforcer.isDeveloperModeActive(context) }
    val tailscaleStatus = remember(context, refreshCount) { NativeEcosystemManager.getTailscaleStatus(context) }
    val memSnapshot = remember(context, refreshCount) { MemoryOptimizer.getMemorySnapshot(context) }

    var envText by remember { mutableStateOf(EnvVaultRepository.readRawText(context)) }
    var filterEnabled by remember { mutableStateOf(DistractionFilterService.isFilterEnabled(context)) }
    var suppressBadges by remember { mutableStateOf(DistractionFilterService.isBadgeSuppressionEnabled(context)) }

    var auditReport by remember { mutableStateOf<SecurityAuditReport?>(null) }
    var scanning by remember { mutableStateOf(false) }

    if (showSshTerminal) {
        SshTerminalDrawer(onClose = { showSshTerminal = false })
        return
    }

    SettingsScaffold(
        title = "TailFin Control Center",
        tag = "tailfin_hub_screen",
        onBack = onBack,
    ) { padding ->
        SettingsList(padding) {
            // 1. Developer Mode & Mesh Status
            item(key = "section_status") {
                SettingsHeading("System & Mesh Status")
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(16.dp))
                        .background(TailFinOrcaGray)
                        .border(1.dp, TailFinOrcaBorder, RoundedCornerShape(16.dp))
                        .padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text(
                        text = "Tailscale Mesh: ${if (tailscaleStatus.vpnActive) "Connected (${tailscaleStatus.tailnetIp ?: "VPN Active"})" else "Standby"}",
                        color = TailFinTextPrimary,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        text = "Developer Mode: ${if (devModeActive) "ENABLED" else "DISABLED (Required)"}",
                        color = if (devModeActive) TailFinMetallicSilver else TailFinAmbientRed,
                        fontSize = 13.sp,
                    )
                    Text(
                        text = "Shizuku Privileged API: ${if (memSnapshot.shizukuAvailable) "Ready" else "Not Bound"}",
                        color = TailFinTextMuted,
                        fontSize = 13.sp,
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(
                            onClick = { showSshTerminal = true },
                            colors = ButtonDefaults.buttonColors(containerColor = TailFinScaleTeal),
                            modifier = Modifier.testTag("open_ssh_drawer_btn"),
                        ) {
                            Text("Open SSH Terminal", color = TailFinTextPrimary)
                        }
                        if (!devModeActive) {
                            OutlinedButton(
                                onClick = { DeveloperModeEnforcer.openDeveloperSettings(context) },
                            ) {
                                Text("Enable Dev Mode", color = TailFinAmbientRed)
                            }
                        }
                    }
                }
            }

            // 2. Zero-Lag Memory Management
            item(key = "section_memory") {
                SettingsHeading("Zero-Lag Memory Management")
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(16.dp))
                        .background(TailFinOrcaGray)
                        .border(1.dp, TailFinOrcaBorder, RoundedCornerShape(16.dp))
                        .padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Text(
                        text = "RAM Usage: ${memSnapshot.usedMb} MB / ${memSnapshot.totalMb} MB (${memSnapshot.usedPercent}%)",
                        color = TailFinTextPrimary,
                        fontWeight = FontWeight.SemiBold,
                    )
                    LinearProgressIndicator(
                        progress = { (memSnapshot.usedPercent / 100f).coerceIn(0f, 1f) },
                        modifier = Modifier.fillMaxWidth().height(8.dp).clip(CircleShape),
                        color = if (memSnapshot.lowMemory) TailFinAmbientRed else TailFinScaleTeal,
                        trackColor = TailFinOrcaSurface,
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(
                            onClick = {
                                val freed = MemoryOptimizer.optimizeIfNeeded(context, force = true) / (1024L * 1024L)
                                refreshCount++
                                Toast.makeText(context, "Freed ${freed}MB background RAM", Toast.LENGTH_SHORT).show()
                            },
                            colors = ButtonDefaults.buttonColors(containerColor = TailFinAmbientRed),
                            modifier = Modifier.testTag("memory_sweep_btn"),
                        ) {
                            Text("Sweep RAM Now", color = TailFinTextPrimary)
                        }
                        OutlinedButton(
                            onClick = {
                                val spec = NativeEcosystemManager.CORE_ECOSYSTEM_APPS.first { it.id == "taskmanager" }
                                NativeEcosystemManager.launchSpec(context, spec)
                            },
                        ) {
                            Text("Open TaskManager", color = TailFinMetallicSilver)
                        }
                    }
                }
            }

            // 3. Distraction-Free Notification Filtering
            item(key = "section_distraction") {
                SettingsHeading("Distraction-Free Notification Filter")
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(16.dp))
                        .background(TailFinOrcaGray)
                        .border(1.dp, TailFinOrcaBorder, RoundedCornerShape(16.dp))
                        .padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text("Strict Distraction Filter", color = TailFinTextPrimary, fontWeight = FontWeight.Medium)
                            Text(
                                "Block promo/social alerts & ongoing bloatware notifications",
                                color = TailFinTextMuted,
                                fontSize = 12.sp,
                            )
                        }
                        Switch(
                            checked = filterEnabled,
                            onCheckedChange = {
                                filterEnabled = it
                                DistractionFilterService.setFilterEnabled(context, it)
                            },
                        )
                    }
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text("Suppress Non-Essential Badges", color = TailFinTextPrimary, fontWeight = FontWeight.Medium)
                            Text(
                                "Only allow badges from Tailscale, Orca, Dicio, K-9 Mail & Phone/SMS",
                                color = TailFinTextMuted,
                                fontSize = 12.sp,
                            )
                        }
                        Switch(
                            checked = suppressBadges,
                            onCheckedChange = {
                                suppressBadges = it
                                DistractionFilterService.setBadgeSuppressionEnabled(context, it)
                            },
                        )
                    }
                }
            }

            // 4. Native Open-Source Application Ecosystem
            item(key = "section_ecosystem") {
                SettingsHeading("Native FOSS Application Ecosystem")
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(16.dp))
                        .background(TailFinOrcaGray)
                        .border(1.dp, TailFinOrcaBorder, RoundedCornerShape(16.dp))
                        .padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    NativeEcosystemManager.CORE_ECOSYSTEM_APPS.forEach { spec ->
                        val installedPkg = remember(context, refreshCount, spec.id) {
                            NativeEcosystemManager.resolveInstalledPackage(context, spec)
                        }
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            Column(modifier = Modifier.weight(1f)) {
                                Text(spec.title, color = TailFinTextPrimary, fontWeight = FontWeight.SemiBold)
                                Text(spec.roleDescription, color = TailFinTextMuted, fontSize = 12.sp)
                                Text(
                                    text = installedPkg ?: "${spec.primaryPackageName} (${if (spec.bundledAssetName != null) "Bundled APK" else "F-Droid"})",
                                    color = TailFinMetallicSilver,
                                    fontFamily = FontFamily.Monospace,
                                    fontSize = 11.sp,
                                )
                            }
                            Spacer(Modifier.width(8.dp))
                            Button(
                                onClick = { NativeEcosystemManager.launchSpec(context, spec) },
                                colors = ButtonDefaults.buttonColors(
                                    containerColor = if (installedPkg != null) TailFinScaleTeal else TailFinAmbientRed
                                ),
                                modifier = Modifier.testTag("ecosystem_app_${spec.id}"),
                            ) {
                                Text(
                                    text = if (installedPkg != null) "Open" else "Install",
                                    color = TailFinTextPrimary,
                                    fontSize = 12.sp,
                                )
                            }
                        }
                    }
                }
            }

            // 5. Hardware-Backed .env Credential Vault
            item(key = "section_env_vault") {
                SettingsHeading("Hardware-Backed .env Credential Vault (AES-256-GCM)")
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(16.dp))
                        .background(TailFinOrcaGray)
                        .border(1.dp, TailFinOrcaBorder, RoundedCornerShape(16.dp))
                        .padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Text(
                        text = "Provider URI: content://com.tailfin.launcher.env\nPermission: com.tailfin.permission.READ_ENV_VAULT\nZero Google Auth dependency — encrypted with Android Keystore AES256_GCM_HKDF_4KB.",
                        color = TailFinTextMuted,
                        fontFamily = FontFamily.Monospace,
                        fontSize = 11.sp,
                    )
                    OutlinedTextField(
                        value = envText,
                        onValueChange = { envText = it },
                        label = { Text(".env Variables (KEY=\"VALUE\")") },
                        textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace),
                        minLines = 6,
                        maxLines = 12,
                        modifier = Modifier.fillMaxWidth().testTag("env_vault_editor"),
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(
                            onClick = {
                                val ok = EnvVaultRepository.writeRawText(context, envText)
                                Toast.makeText(
                                    context,
                                    if (ok) "Encrypted .env vault saved" else "Failed to save .env vault",
                                    Toast.LENGTH_SHORT,
                                ).show()
                            },
                            colors = ButtonDefaults.buttonColors(containerColor = TailFinScaleTeal),
                            modifier = Modifier.testTag("env_vault_save_btn"),
                        ) {
                            Text("Save Encrypted .env", color = TailFinTextPrimary)
                        }
                        OutlinedButton(
                            onClick = { envText = EnvVaultRepository.DEFAULT_ENV_TEMPLATE },
                        ) {
                            Text("Reset Template", color = TailFinMetallicSilver)
                        }
                    }
                }
            }

            // 6. Lite Security Scanner
            item(key = "section_security_scanner") {
                SettingsHeading("Lite Security Scanner")
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(16.dp))
                        .background(TailFinOrcaGray)
                        .border(1.dp, TailFinOrcaBorder, RoundedCornerShape(16.dp))
                        .padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Text(
                        text = "Audits installed packages for high-risk permissions (SYSTEM_ALERT_WINDOW, BIND_ACCESSIBILITY_SERVICE, READ_LOGS, REQUEST_INSTALL_PACKAGES), telemetry combinations, and untrusted installers.",
                        color = TailFinTextMuted,
                        fontSize = 12.sp,
                    )
                    Button(
                        enabled = !scanning,
                        onClick = {
                            scanning = true
                            scope.launch {
                                val report = withContext(Dispatchers.IO) {
                                    LiteSecurityScanner.scanInstalledPackages(context)
                                }
                                auditReport = report
                                scanning = false
                            }
                        },
                        colors = ButtonDefaults.buttonColors(containerColor = TailFinAmbientRed),
                        modifier = Modifier.testTag("run_security_scan_btn"),
                    ) {
                        Text(if (scanning) "Scanning Packages…" else "Run On-Device Security Audit", color = TailFinTextPrimary)
                    }

                    val report = auditReport
                    if (report != null) {
                        Text(
                            text = "Scanned ${report.scannedPackagesCount} user apps · High Risk: ${report.highRiskCount} · Telemetry Combos: ${report.telemetryComboCount} · Untrusted Installer: ${report.untrustedInstallerCount}",
                            color = TailFinMetallicSilver,
                            fontWeight = FontWeight.SemiBold,
                            fontSize = 13.sp,
                        )
                        report.flaggedPackages.take(15).forEach { finding ->
                            Column(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(8.dp))
                                    .background(TailFinOrcaSurface)
                                    .padding(10.dp),
                            ) {
                                Text(
                                    text = "${finding.appLabel} [${finding.riskLevel}]",
                                    color = when (finding.riskLevel) {
                                        SecurityRiskLevel.HIGH -> TailFinAmbientRed
                                        SecurityRiskLevel.MEDIUM -> TailFinMetallicSilver
                                        SecurityRiskLevel.LOW -> TailFinTextMuted
                                    },
                                    fontWeight = FontWeight.Bold,
                                    fontSize = 13.sp,
                                )
                                Text(
                                    text = finding.packageName,
                                    color = TailFinTextMuted,
                                    fontFamily = FontFamily.Monospace,
                                    fontSize = 11.sp,
                                )
                                if (finding.highRiskPermissions.isNotEmpty()) {
                                    Text(
                                        text = "Permissions: ${finding.highRiskPermissions.joinToString { it.substringAfterLast('.') }}",
                                        color = TailFinTextPrimary,
                                        fontSize = 11.sp,
                                    )
                                }
                                if (finding.hasTelemetryCombo) {
                                    Text(
                                        text = "Telemetry Alert: INTERNET + FINE_LOCATION + READ_PHONE_STATE",
                                        color = TailFinAmbientRed,
                                        fontSize = 11.sp,
                                    )
                                }
                                if (!finding.trustedInstaller) {
                                    Text(
                                        text = "Installer: ${finding.installerPackage ?: "sideload/unknown"}",
                                        color = TailFinTextMuted,
                                        fontSize = 11.sp,
                                    )
                                }
                            }
                        }
                    }
                }
                Spacer(Modifier.height(24.dp))
            }
        }
    }
}
