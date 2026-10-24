package com.tailfin.launcher.terminal

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.galaxyrio.gracelauncher.ui.theme.TailFinAmbientRed
import com.galaxyrio.gracelauncher.ui.theme.TailFinMetallicSilver
import com.galaxyrio.gracelauncher.ui.theme.TailFinOrcaBorder
import com.galaxyrio.gracelauncher.ui.theme.TailFinOrcaGray
import com.galaxyrio.gracelauncher.ui.theme.TailFinOrcaSurface
import com.galaxyrio.gracelauncher.ui.theme.TailFinScaleTeal
import com.galaxyrio.gracelauncher.ui.theme.TailFinTextMuted
import com.galaxyrio.gracelauncher.ui.theme.TailFinTextPrimary
import com.galaxyrio.gracelauncher.ui.theme.TailFinVoidBlack
import com.jcraft.jsch.ChannelShell
import com.jcraft.jsch.JSch
import com.jcraft.jsch.Session
import com.tailfin.launcher.security.EnvVaultRepository
import java.io.File
import java.io.OutputStream
import java.util.Properties
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class JSchTerminalClient(
    private val scope: CoroutineScope,
    private val onOutput: (String) -> Unit,
    private val onStateChange: (Boolean, String) -> Unit,
) {
    private var session: Session? = null
    private var channel: ChannelShell? = null
    private var outputStream: OutputStream? = null
    private var readerJob: Job? = null

    fun connect(
        host: String,
        port: Int,
        user: String,
        password: String,
        keyPath: String,
    ) {
        disconnect()
        onStateChange(false, "Connecting to $user@$host:$port…")
        readerJob = scope.launch(Dispatchers.IO) {
            runCatching {
                val jsch = JSch()
                if (keyPath.isNotBlank() && File(keyPath).canRead()) {
                    jsch.addIdentity(keyPath)
                }
                val newSession = jsch.getSession(user, host, port)
                if (password.isNotBlank()) {
                    newSession.setPassword(password)
                }
                val config = Properties().apply {
                    put("StrictHostKeyChecking", "no")
                }
                newSession.setConfig(config)
                newSession.connect(10_000)

                val shell = newSession.openChannel("shell") as ChannelShell
                shell.setPtyType("xterm-256color")
                val input = shell.inputStream
                val out = shell.outputStream
                shell.connect(5_000)

                session = newSession
                channel = shell
                outputStream = out

                withContext(Dispatchers.Main) {
                    onStateChange(true, "Connected: $user@$host:$port")
                    onOutput("\n[TailFin SSH] Connected to $user@$host:$port over Tailscale\n")
                }

                val buffer = ByteArray(4096)
                while (isActive && shell.isConnected) {
                    val read = input.read(buffer)
                    if (read <= 0) break
                    val chunk = String(buffer, 0, read, Charsets.UTF_8)
                    withContext(Dispatchers.Main) {
                        onOutput(chunk)
                    }
                }
            }.onFailure { err ->
                withContext(Dispatchers.Main) {
                    onStateChange(false, "Disconnected: ${err.localizedMessage ?: "error"}")
                    onOutput("\n[TailFin SSH Error] ${err.localizedMessage}\n")
                }
            }
            withContext(Dispatchers.Main) {
                onStateChange(false, "Disconnected")
            }
        }
    }

    fun sendRaw(sequence: String) {
        scope.launch(Dispatchers.IO) {
            runCatching {
                outputStream?.write(sequence.toByteArray(Charsets.UTF_8))
                outputStream?.flush()
            }
        }
    }

    fun disconnect() {
        readerJob?.cancel()
        readerJob = null
        scope.launch(Dispatchers.IO) {
            runCatching { outputStream?.close() }
            runCatching { channel?.disconnect() }
            runCatching { session?.disconnect() }
        }
        outputStream = null
        channel = null
        session = null
    }
}

@Composable
fun SshTerminalDrawer(
    onClose: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val initialConfig = remember(context) { EnvVaultRepository.getSshConfig(context) }

    var host by remember { mutableStateOf(initialConfig.host) }
    var user by remember { mutableStateOf(initialConfig.user) }
    var portText by remember { mutableStateOf(initialConfig.port.toString()) }
    var password by remember { mutableStateOf(initialConfig.password) }
    var keyPath by remember { mutableStateOf(initialConfig.keyPath) }
    var showConnectionSettings by remember { mutableStateOf(false) }

    var connected by remember { mutableStateOf(false) }
    var statusText by remember { mutableStateOf("Ready (${initialConfig.user}@${initialConfig.host}:${initialConfig.port})") }
    var terminalBuffer by remember {
        mutableStateOf(
            buildString {
                appendLine("TailFin Integrated Mobile SSH Terminal")
                appendLine("Loaded from .env vault -> SSH_HOST=${initialConfig.host}, SSH_USER=${initialConfig.user}, SSH_PORT=${initialConfig.port}")
                appendLine("Tap 'Connect' to open an interactive shell over Tailscale (100.x.y.z).")
                appendLine("------------------------------------------------------------")
            }
        )
    }
    var commandInput by remember { mutableStateOf("") }
    var ctrlSticky by remember { mutableStateOf(false) }
    var altSticky by remember { mutableStateOf(false) }

    val scrollState = rememberScrollState()
    val client = remember {
        JSchTerminalClient(
            scope = scope,
            onOutput = { chunk ->
                terminalBuffer = (terminalBuffer + chunk).takeLast(24_000)
            },
            onStateChange = { isConnected, status ->
                connected = isConnected
                statusText = status
            },
        )
    }

    DisposableEffect(Unit) {
        onDispose { client.disconnect() }
    }

    LaunchedEffect(terminalBuffer.length) {
        scrollState.animateScrollTo(scrollState.maxValue)
    }

    fun dispatchInput(raw: String, appendNewline: Boolean = false) {
        val modified = MobileTerminalKeyEncoder.applyModifiers(raw, ctrlSticky, altSticky)
        ctrlSticky = false
        altSticky = false
        val payload = if (appendNewline) "$modified\n" else modified
        if (connected) {
            client.sendRaw(payload)
        } else {
            terminalBuffer += "\n$ $raw\n[Not connected — tap Connect to open SSH session]\n"
        }
    }

    Surface(
        modifier = modifier
            .fillMaxSize()
            .imePadding()
            .navigationBarsPadding()
            .testTag("ssh_terminal_drawer"),
        color = TailFinVoidBlack,
        contentColor = TailFinTextPrimary,
    ) {
        Column(modifier = Modifier.fillMaxSize()) {
            // Header bar
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(TailFinOrcaSurface)
                    .padding(horizontal = 16.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = "TailFin SSH Terminal",
                        color = TailFinMetallicSilver,
                        fontWeight = FontWeight.Bold,
                        fontSize = 16.sp,
                    )
                    Text(
                        text = statusText,
                        color = if (connected) TailFinScaleTeal else TailFinTextMuted,
                        fontFamily = FontFamily.Monospace,
                        fontSize = 11.sp,
                    )
                }
                TextButton(onClick = { showConnectionSettings = !showConnectionSettings }) {
                    Text(if (showConnectionSettings) "Hide Host" else "Host Config", color = TailFinMetallicSilver)
                }
                Spacer(Modifier.width(4.dp))
                if (connected) {
                    OutlinedButton(
                        onClick = { client.disconnect() },
                        modifier = Modifier.testTag("ssh_disconnect_btn"),
                    ) {
                        Text("Disconnect", color = TailFinAmbientRed)
                    }
                } else {
                    Button(
                        onClick = {
                            val port = portText.toIntOrNull()?.coerceIn(1, 65535) ?: 22
                            client.connect(host.trim(), port, user.trim(), password, keyPath.trim())
                        },
                        colors = ButtonDefaults.buttonColors(containerColor = TailFinScaleTeal),
                        modifier = Modifier.testTag("ssh_connect_btn"),
                    ) {
                        Text("Connect", color = TailFinTextPrimary)
                    }
                }
                Spacer(Modifier.width(4.dp))
                TextButton(onClick = onClose, modifier = Modifier.testTag("ssh_close_btn")) {
                    Text("Close", color = TailFinAmbientRed)
                }
            }

            if (showConnectionSettings) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(TailFinOrcaGray)
                        .padding(12.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(
                            value = host,
                            onValueChange = { host = it },
                            label = { Text("SSH_HOST (Tailscale IP/MagicDNS)") },
                            singleLine = true,
                            modifier = Modifier.weight(2f),
                        )
                        OutlinedTextField(
                            value = portText,
                            onValueChange = { portText = it },
                            label = { Text("SSH_PORT") },
                            singleLine = true,
                            modifier = Modifier.weight(1f),
                        )
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(
                            value = user,
                            onValueChange = { user = it },
                            label = { Text("SSH_USER") },
                            singleLine = true,
                            modifier = Modifier.weight(1f),
                        )
                        OutlinedTextField(
                            value = password,
                            onValueChange = { password = it },
                            label = { Text("Password (optional)") },
                            singleLine = true,
                            visualTransformation = PasswordVisualTransformation(),
                            modifier = Modifier.weight(1f),
                        )
                    }
                    OutlinedTextField(
                        value = keyPath,
                        onValueChange = { keyPath = it },
                        label = { Text("SSH_KEY_PATH (private key path)") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }

            // Terminal Output Viewport
            Box(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .padding(8.dp)
                    .border(1.dp, TailFinOrcaBorder, RoundedCornerShape(8.dp))
                    .background(TailFinVoidBlack, RoundedCornerShape(8.dp))
                    .padding(12.dp)
                    .verticalScroll(scrollState),
            ) {
                Text(
                    text = terminalBuffer,
                    color = TailFinTextPrimary,
                    fontFamily = FontFamily.Monospace,
                    fontSize = 13.sp,
                    lineHeight = 18.sp,
                    modifier = Modifier.testTag("ssh_terminal_output"),
                )
            }

            // Mobile Developer KeyBar docked directly above command input / soft keyboard
            MobileKeyBarView(
                ctrlSticky = ctrlSticky,
                altSticky = altSticky,
                onToggleCtrl = { ctrlSticky = !ctrlSticky },
                onToggleAlt = { altSticky = !altSticky },
                onSendSequence = { seq -> dispatchInput(seq, appendNewline = false) },
            )

            // Command Input Row
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(TailFinOrcaSurface)
                    .padding(horizontal = 12.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                OutlinedTextField(
                    value = commandInput,
                    onValueChange = { commandInput = it },
                    placeholder = {
                        Text(
                            if (ctrlSticky || altSticky) {
                                "Modifier active (${if (ctrlSticky) "CTRL " else ""}${if (altSticky) "ALT" else ""})…"
                            } else {
                                "Enter shell command…"
                            },
                            fontFamily = FontFamily.Monospace,
                            fontSize = 13.sp,
                        )
                    },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                    keyboardActions = KeyboardActions(
                        onSend = {
                            dispatchInput(commandInput, appendNewline = true)
                            commandInput = ""
                        }
                    ),
                    modifier = Modifier
                        .weight(1f)
                        .testTag("ssh_command_input"),
                )
                Button(
                    onClick = {
                        dispatchInput(commandInput, appendNewline = true)
                        commandInput = ""
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = TailFinAmbientRed),
                    modifier = Modifier.height(52.dp).testTag("ssh_send_btn"),
                ) {
                    Text("Send", color = TailFinTextPrimary)
                }
            }
        }
    }
}
