package com.tailfin.launcher.security

import android.content.ContentProvider
import android.content.ContentValues
import android.content.Context
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri
import androidx.security.crypto.EncryptedFile
import androidx.security.crypto.MasterKeys
import java.io.File

data class EnvEntry(
    val key: String,
    val value: String,
)

data class SshEnvConfig(
    val host: String = "100.64.0.1",
    val user: String = "root",
    val port: Int = 22,
    val password: String = "",
    val keyPath: String = "",
)

object EnvVaultRepository {

    const val ENV_FILE_NAME = ".env"
    const val AUTHORITY = "com.tailfin.launcher.env"
    val AUTHORITY_URI: Uri get() = Uri.parse("content://$AUTHORITY")

    val DEFAULT_ENV_TEMPLATE = """
        # TailFin Hardware-Backed .env Credential Vault
        # Accessible only to apps holding com.tailfin.permission.READ_ENV_VAULT
        SSH_HOST="100.64.0.1"
        SSH_USER="mrnicholas"
        SSH_PORT="22"
        SSH_KEY_PATH=""
        ORCA_AGENT_URL="http://100.64.0.1:8080"
        ORCA_API_KEY=""
        TAILSCALE_TAILNET="local.ts.net"
    """.trimIndent()

    internal fun getEncryptedEnvFile(context: Context): EncryptedFile {
        val appCtx = context.applicationContext
        @Suppress("DEPRECATION")
        val masterKeyAlias = MasterKeys.getOrCreate(MasterKeys.AES256_GCM_SPEC)
        val file = File(appCtx.filesDir, ENV_FILE_NAME)
        @Suppress("DEPRECATION")
        return EncryptedFile.Builder(
            file,
            appCtx,
            masterKeyAlias,
            EncryptedFile.FileEncryptionScheme.AES256_GCM_HKDF_4KB
        ).build()
    }

    fun parseEnvLines(lines: Sequence<String>): List<EnvEntry> {
        val entries = mutableListOf<EnvEntry>()
        lines.forEach { line ->
            val trimmed = line.trim()
            if (trimmed.isNotEmpty() && !trimmed.startsWith("#") && trimmed.contains("=")) {
                val key = trimmed.substringBefore("=").trim()
                val value = trimmed.substringAfter("=").trim()
                    .removeSurrounding("\"")
                    .removeSurrounding("'")
                if (key.isNotEmpty()) {
                    entries.add(EnvEntry(key, value))
                }
            }
        }
        return entries
    }

    fun parseEnvText(text: String): List<EnvEntry> =
        parseEnvLines(text.lineSequence())

    fun formatEnvEntries(entries: List<EnvEntry>): String = buildString {
        appendLine("# TailFin Hardware-Backed .env Credential Vault")
        entries.forEach { (key, value) ->
            val cleanKey = key.trim()
            if (cleanKey.isNotEmpty()) {
                appendLine("$cleanKey=\"${value.replace("\"", "\\\"")}\"")
            }
        }
    }

    @Synchronized
    fun readRawText(context: Context): String {
        val envFile = File(context.applicationContext.filesDir, ENV_FILE_NAME)
        if (!envFile.exists()) return DEFAULT_ENV_TEMPLATE
        return runCatching {
            getEncryptedEnvFile(context).openFileInput().bufferedReader().use { it.readText() }
        }.getOrDefault(DEFAULT_ENV_TEMPLATE)
    }

    @Synchronized
    fun writeRawText(context: Context, rawContent: String): Boolean {
        return runCatching {
            val envFile = File(context.applicationContext.filesDir, ENV_FILE_NAME)
            if (envFile.exists()) {
                envFile.delete()
            }
            getEncryptedEnvFile(context).openFileOutput().bufferedWriter().use { writer ->
                writer.write(rawContent)
            }
            true
        }.getOrDefault(false)
    }

    @Synchronized
    fun readEntries(context: Context): List<EnvEntry> {
        val envFile = File(context.applicationContext.filesDir, ENV_FILE_NAME)
        if (!envFile.exists()) return parseEnvText(DEFAULT_ENV_TEMPLATE)
        return runCatching {
            getEncryptedEnvFile(context).openFileInput().bufferedReader().useLines { lines ->
                parseEnvLines(lines)
            }
        }.getOrElse { parseEnvText(DEFAULT_ENV_TEMPLATE) }
    }

    @Synchronized
    fun readMap(context: Context): Map<String, String> =
        readEntries(context).associate { it.key to it.value }

    fun getSshConfig(context: Context): SshEnvConfig {
        val map = readMap(context)
        return SshEnvConfig(
            host = map["SSH_HOST"]?.takeIf { it.isNotBlank() } ?: "100.64.0.1",
            user = map["SSH_USER"]?.takeIf { it.isNotBlank() } ?: "root",
            port = map["SSH_PORT"]?.toIntOrNull()?.coerceIn(1, 65535) ?: 22,
            password = map["SSH_PASSWORD"].orEmpty(),
            keyPath = map["SSH_KEY_PATH"].orEmpty(),
        )
    }
}

class EnvVaultContentProvider : ContentProvider() {

    private fun getEncryptedEnvFile(): EncryptedFile =
        EnvVaultRepository.getEncryptedEnvFile(requireContext())

    override fun query(
        uri: Uri, projection: Array<out String>?, selection: String?,
        selectionArgs: Array<out String>?, sortOrder: String?
    ): Cursor {
        val cursor = MatrixCursor(arrayOf("KEY", "VALUE"))
        val envFile = File(requireContext().filesDir, ".env")
        if (!envFile.exists()) return cursor

        runCatching {
            getEncryptedEnvFile().openFileInput().bufferedReader().useLines { lines ->
                EnvVaultRepository.parseEnvLines(lines).forEach { entry ->
                    if (selection == null || entry.key == selection || selectionArgs?.contains(entry.key) == true) {
                        cursor.addRow(arrayOf(entry.key, entry.value))
                    }
                }
            }
        }
        return cursor
    }

    override fun onCreate(): Boolean = true
    override fun getType(uri: Uri): String = "vnd.android.cursor.dir/vnd.tailfin.env"
    override fun insert(uri: Uri, values: ContentValues?): Uri? = null
    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int = 0
    override fun update(uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?): Int = 0
}
