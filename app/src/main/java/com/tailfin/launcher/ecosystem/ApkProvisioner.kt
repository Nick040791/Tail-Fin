package com.tailfin.launcher.ecosystem

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.net.Uri
import android.os.Build
import android.widget.Toast
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

object ApkProvisioner {

    private val scope = CoroutineScope(Dispatchers.IO)

    fun hasBundledAsset(context: Context, assetApkPath: String): Boolean = runCatching {
        context.assets.openFd(assetApkPath).use { true }
    }.getOrElse {
        runCatching {
            context.assets.open(assetApkPath).use { true }
        }.getOrDefault(false)
    }

    fun installBundledApk(context: Context, assetApkPath: String, fallbackPackageName: String? = null) {
        val appContext = context.applicationContext
        if (!hasBundledAsset(appContext, assetApkPath)) {
            if (fallbackPackageName != null) {
                openInFDroidOrBrowser(appContext, fallbackPackageName)
            } else {
                Toast.makeText(appContext, "Bundled APK not found: $assetApkPath", Toast.LENGTH_SHORT).show()
            }
            return
        }

        Toast.makeText(appContext, "Provisioning ${assetApkPath.substringAfterLast('/')}…", Toast.LENGTH_SHORT).show()

        scope.launch {
            val result = runCatching {
                val packageInstaller = appContext.packageManager.packageInstaller
                val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
                val sessionId = packageInstaller.createSession(params)
                packageInstaller.openSession(sessionId).use { session ->
                    appContext.assets.open(assetApkPath).use { input ->
                        session.openWrite("tailfin_provision.apk", 0, -1).use { output ->
                            input.copyTo(output)
                            session.fsync(output)
                        }
                    }
                    val callbackIntent = Intent(appContext, ApkInstallStatusReceiver::class.java).apply {
                        action = ApkInstallStatusReceiver.ACTION_INSTALL_STATUS
                        putExtra(ApkInstallStatusReceiver.EXTRA_ASSET_PATH, assetApkPath)
                    }
                    val flags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE
                    } else {
                        PendingIntent.FLAG_UPDATE_CURRENT
                    }
                    val pendingIntent = PendingIntent.getBroadcast(
                        appContext,
                        sessionId,
                        callbackIntent,
                        flags,
                    )
                    session.commit(pendingIntent.intentSender)
                }
            }
            if (result.isFailure) {
                withContext(Dispatchers.Main) {
                    if (fallbackPackageName != null) {
                        openInFDroidOrBrowser(appContext, fallbackPackageName)
                    } else {
                        Toast.makeText(
                            appContext,
                            "APK provisioning failed: ${result.exceptionOrNull()?.localizedMessage}",
                            Toast.LENGTH_LONG,
                        ).show()
                    }
                }
            }
        }
    }

    fun openInFDroidOrBrowser(context: Context, packageName: String) {
        val fdroidIntent = Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=$packageName")).apply {
            setPackage(NativeEcosystemManager.PKG_FDROID)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        if (fdroidIntent.resolveActivity(context.packageManager) != null) {
            context.startActivity(fdroidIntent)
            return
        }
        val webIntent = Intent(Intent.ACTION_VIEW, Uri.parse("https://f-droid.org/packages/$packageName/")).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        runCatching { context.startActivity(webIntent) }.onFailure {
            Toast.makeText(context, "Install F-Droid to provision $packageName", Toast.LENGTH_SHORT).show()
        }
    }
}

class ApkInstallStatusReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != ACTION_INSTALL_STATUS) return
        val status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)
        when (status) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                @Suppress("DEPRECATION")
                val confirmIntent = intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)
                if (confirmIntent != null) {
                    confirmIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    runCatching { context.startActivity(confirmIntent) }
                }
            }
            PackageInstaller.STATUS_SUCCESS -> {
                Toast.makeText(context, "TailFin FOSS app installed successfully", Toast.LENGTH_SHORT).show()
            }
            else -> {
                val msg = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE) ?: "Installation cancelled or failed"
                Toast.makeText(context, msg, Toast.LENGTH_SHORT).show()
            }
        }
    }

    companion object {
        const val ACTION_INSTALL_STATUS = "com.tailfin.launcher.action.APK_INSTALL_STATUS"
        const val EXTRA_ASSET_PATH = "extra_asset_path"
    }
}
