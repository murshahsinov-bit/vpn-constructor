package com.v2ray.ang.ui.settings

import android.app.Application
import android.content.Intent
import android.provider.Settings
import com.v2ray.ang.AppConfig
import com.v2ray.ang.R
import com.v2ray.ang.handler.MmkvManager
import com.v2ray.ang.root.RootManager
import com.v2ray.ang.shield.ShieldConfig
import com.v2ray.ang.shield.ShieldPrefs
import com.v2ray.ang.shield.ShieldRepository
import com.v2ray.ang.ui.base.BaseViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext

class SettingsViewModel(application: Application) : BaseViewModel(application) {

    private val _systemVpnSettingsAvailable = MutableStateFlow(false)
    val systemVpnSettingsAvailable = _systemVpnSettingsAvailable.asStateFlow()

    /** Epoch millis of the last successful subscription download, 0 when never. */
    private val _lastUpdated = MutableStateFlow(0L)
    val lastUpdated = _lastUpdated.asStateFlow()

    suspend fun refreshSystemVpnSettingsAvailability() {
        _systemVpnSettingsAvailable.value = withContext(Dispatchers.IO) {
            // Android exposes the VPN page, not a direct link to the Always-on VPN switch.
            Intent(Settings.ACTION_VPN_SETTINGS).resolveActivity(getApplication<Application>().packageManager) != null
        }
    }

    /** Reads the cached subscription timestamp so the screen can show it. */
    suspend fun loadSubscriptionState() {
        _lastUpdated.value = withContext(Dispatchers.IO) { cachedLastUpdated() }
    }

    /**
     * Downloads the per-account subscription again. Runs off the main thread and
     * reports the new server count through a toast, so the settings screen does
     * not need to own any network code.
     */
    fun refreshSubscription() {
        if (_isLoading.value) return
        launchLoading {
            val result = withContext(Dispatchers.IO) {
                runCatching { ShieldRepository.refreshSubscription() }
            }
            result.onSuccess { count ->
                // A new list can have different nodes: re-rank on the next connect.
                withContext(Dispatchers.IO) {
                    ShieldPrefs.setServerRanked(false)
                    _lastUpdated.value = cachedLastUpdated()
                }
                toastSuccess(getString(R.string.shield_subscription_refreshed, count))
            }.onFailure { error ->
                toastError(error.message ?: getString(R.string.shield_subscription_failed))
            }
        }
    }

    private fun cachedLastUpdated(): Long =
        MmkvManager.decodeSubscription(ShieldConfig.SUBSCRIPTION_ID)?.lastUpdated ?: 0L

    /**
     * Checks for root access and requests it if necessary.
     * Updates [isLoading] during the process.
     */
    fun checkAndRequestRoot(onSuccess: () -> Unit) {
        launchLoading {
            val hasRoot = withContext(Dispatchers.IO) {
                RootManager.refresh()
            }
            if (hasRoot) {
                onSuccess()
            } else {
                toastError(R.string.toast_root_required)
            }
        }
    }

    /**
     * Validates if the given string is a valid observatory duration.
     * Shows error toast if invalid.
     * @return The trimmed value if valid, null otherwise.
     */
    fun validateObservatoryDuration(value: String): String? {
        val duration = value.trim()
        return if (AppConfig.OBSERVATORY_DURATION_PATTERN.matches(duration)) {
            duration
        } else {
            toastError(R.string.toast_invalid_observatory_duration)
            null
        }
    }

    /**
     * Validates if the given string is a valid observatory sampling value.
     * Shows error toast if invalid.
     * @return The value if valid, null otherwise.
     */
    fun validateObservatorySampling(value: String): String? {
        val sampling = value.trim().toIntOrNull()?.takeIf { it > 0 }
        return if (sampling != null) {
            sampling.toString()
        } else {
            toastError(R.string.toast_invalid_observatory_sampling)
            null
        }
    }
}
