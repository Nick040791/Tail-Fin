package com.tailfin.launcher.memory

import android.app.Service
import android.content.Intent
import android.os.IBinder
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Lightweight background memory monitor that periodically sweeps non-protected
 * background processes when available RAM drops below the 22% threshold.
 */
class MemoryOptimizerService : Service() {

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    override fun onCreate() {
        super.onCreate()
        serviceScope.launch {
            while (isActive) {
                runCatching {
                    MemoryOptimizer.optimizeIfNeeded(applicationContext, force = false)
                }
                delay(SWEEP_INTERVAL_MS)
            }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val force = intent?.getBooleanExtra(EXTRA_FORCE_SWEEP, false) == true
        serviceScope.launch {
            runCatching {
                MemoryOptimizer.optimizeIfNeeded(applicationContext, force = force)
            }
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        serviceScope.cancel()
        super.onDestroy()
    }

    companion object {
        const val EXTRA_FORCE_SWEEP = "extra_force_sweep"
        private const val SWEEP_INTERVAL_MS = 5 * 60 * 1000L
    }
}
