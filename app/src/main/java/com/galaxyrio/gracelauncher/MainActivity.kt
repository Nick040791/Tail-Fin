package com.galaxyrio.gracelauncher

import android.app.WallpaperManager
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.view.MotionEvent
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.lifecycleScope
import com.galaxyrio.gracelauncher.platform.LauncherAppTransitions
import com.galaxyrio.gracelauncher.ui.LauncherAppTheme
import com.galaxyrio.gracelauncher.ui.LauncherRoute
import com.galaxyrio.gracelauncher.ui.LauncherViewModel
import com.galaxyrio.gracelauncher.ui.components.LocalAppTransitions
import com.tailfin.launcher.assistant.DefaultAssistantEnforcer
import com.tailfin.launcher.devmode.DeveloperModeEnforcer
import com.tailfin.launcher.memory.MemoryOptimizer
import com.tailfin.launcher.permissions.TailFinPermissionCoordinator
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    private val launcherViewModel: LauncherViewModel by viewModels()
    private var widgetEditRequest by mutableIntStateOf(0)
    private val appTransitions by lazy { LauncherAppTransitions(this, lifecycleScope) }

    private val firstLaunchPermissionsLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) {
        launcherViewModel.refreshOnResume()
        launcherViewModel.refreshSchedule()
        DefaultAssistantEnforcer.verifyAndPrompt(this)
        DeveloperModeEnforcer.verifyAndPrompt(this)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        applyDefaultTailFinWallpaperOnce()
        requestFirstLaunchPermissionsIfNeeded()
        if (intent.getBooleanExtra(EXTRA_EDIT_WIDGET, false)) { widgetEditRequest++; intent.removeExtra(EXTRA_EDIT_WIDGET) }
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
        )
        setContent {
            CompositionLocalProvider(LocalAppTransitions provides appTransitions) {
                LauncherAppTheme(launcherViewModel) {
                    LauncherRoute(viewModel = launcherViewModel, widgetEditRequest = widgetEditRequest)
                }
            }
        }
        appTransitions.onHomeIntent(intent)
    }

    override fun onResume() {
        super.onResume()
        if (!TailFinPermissionCoordinator.isFirstLaunchPermissionPending(this)) {
            DefaultAssistantEnforcer.verifyAndPrompt(this)
            DeveloperModeEnforcer.verifyAndPrompt(this)
        }
        MemoryOptimizer.optimizeIfNeeded(this)
        launcherViewModel.refreshOnResume()
        launcherViewModel.refreshSchedule()
    }

    private fun requestFirstLaunchPermissionsIfNeeded() {
        if (!TailFinPermissionCoordinator.isFirstLaunchPermissionPending(this)) return
        TailFinPermissionCoordinator.markFirstLaunchPermissionsRequested(this)
        val missing = TailFinPermissionCoordinator.getMissingRuntimePermissions(this)
        if (missing.isNotEmpty()) {
            runCatching { firstLaunchPermissionsLauncher.launch(missing) }
        } else {
            DefaultAssistantEnforcer.verifyAndPrompt(this)
            DeveloperModeEnforcer.verifyAndPrompt(this)
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (intent.getBooleanExtra(EXTRA_EDIT_WIDGET, false)) { widgetEditRequest++; intent.removeExtra(EXTRA_EDIT_WIDGET) }
        if (intent.action == Intent.ACTION_MAIN && intent.hasCategory(Intent.CATEGORY_HOME)) {
            launcherViewModel.requestReturnHome()
            appTransitions.onHomeIntent(intent)
        }
    }

    override fun onPause() {
        appTransitions.close()
        super.onPause()
    }

    override fun onDestroy() {
        appTransitions.close()
        super.onDestroy()
    }

    override fun dispatchTouchEvent(event: MotionEvent): Boolean {
        if (event.actionMasked == MotionEvent.ACTION_DOWN) appTransitions.close()
        return super.dispatchTouchEvent(event)
    }

    private fun applyDefaultTailFinWallpaperOnce() {
        val prefs = getSharedPreferences("tailfin_wallpaper_prefs", MODE_PRIVATE)
        if (!prefs.getBoolean("default_wallpaper_applied", false)) {
            lifecycleScope.launch(Dispatchers.IO) {
                runCatching {
                    WallpaperManager.getInstance(applicationContext)
                        .setResource(com.tailfin.launcher.R.drawable.tailfin_launcher_background)
                    prefs.edit().putBoolean("default_wallpaper_applied", true).apply()
                }
            }
        }
    }

    companion object { const val EXTRA_EDIT_WIDGET = "editHomeWidget" }
}
