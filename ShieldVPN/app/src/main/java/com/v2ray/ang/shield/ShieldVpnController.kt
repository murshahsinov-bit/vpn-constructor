package com.v2ray.ang.shield

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import androidx.core.content.ContextCompat
import com.v2ray.ang.AppConfig
import com.v2ray.ang.R
import com.v2ray.ang.core.LauncherManager
import com.v2ray.ang.handler.SettingsManager
import com.v2ray.ang.helper.MessageHelper
import com.v2ray.ang.util.LogUtil
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull

enum class ShieldStatus {
    Idle,
    Connecting,
    Connected,
    Disconnecting,
    Error,
}

data class ShieldUiState(
    val status: ShieldStatus = ShieldStatus.Idle,
    val servers: List<ShieldServer> = emptyList(),
    val selectedGuid: String? = null,
    val selectedTitle: String? = null,
    val attempt: Int = 0,
    val totalAttempts: Int = 0,
    val message: String? = null,
    val autoConnect: Boolean = true,
    /** False until the daemon has been asked whether the tunnel is already up. */
    val initialized: Boolean = false,
)

/**
 * Owns the whole connection lifecycle:
 *
 * 1. import/refresh the baked-in subscription,
 * 2. start the daemon for a server,
 * 3. verify the tunnel with a real SOCKS5 probe,
 * 4. on timeout/failure move to the next server from the subscription.
 */
class ShieldVpnController(private val context: Context) {

    private val _state = MutableStateFlow(ShieldUiState(autoConnect = ShieldPrefs.isAutoConnect()))
    val state: StateFlow<ShieldUiState> = _state.asStateFlow()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val events = Channel<Int>(Channel.UNLIMITED)

    private var attachCount = 0
    private var connectJob: Job? = null
    private var serviceRunning = false

    private val receiver = object : BroadcastReceiver() {
        override fun onReceive(receiverContext: Context?, intent: Intent?) {
            val key = intent?.getIntExtra("key", -1) ?: return
            when (key) {
                AppConfig.MSG_STATE_RUNNING, AppConfig.MSG_STATE_START_SUCCESS -> serviceRunning = true
                AppConfig.MSG_STATE_NOT_RUNNING,
                AppConfig.MSG_STATE_STOP_SUCCESS,
                AppConfig.MSG_STATE_START_FAILURE,
                -> serviceRunning = false
            }
            events.trySend(key)
        }
    }

    // ------------------------------------------------------------------ lifecycle

    fun attach() {
        if (attachCount++ > 0) return
        ContextCompat.registerReceiver(
            context,
            receiver,
            IntentFilter(AppConfig.BROADCAST_ACTION_ACTIVITY),
            ContextCompat.RECEIVER_NOT_EXPORTED,
        )
        refreshServers()
        scope.launch {
            drain()
            MessageHelper.sendMsg2Service(context, AppConfig.MSG_REGISTER_CLIENT, "")
            val key = withTimeoutOrNull(1_500) { events.receive() }
            when (key) {
                AppConfig.MSG_STATE_RUNNING -> {
                    serviceRunning = true
                    _state.update {
                        it.copy(
                            status = ShieldStatus.Connected,
                            selectedGuid = ShieldRepository.selectedGuid(),
                            selectedTitle = ShieldRepository.selectedServer()?.title,
                            initialized = true,
                        )
                    }
                }

                AppConfig.MSG_STATE_NOT_RUNNING -> {
                    serviceRunning = false
                    _state.update { it.copy(status = ShieldStatus.Idle, initialized = true) }
                }

                else -> _state.update { it.copy(status = ShieldStatus.Idle, initialized = true) }
            }
        }
    }

    fun detach() {
        if (attachCount == 0) return
        if (--attachCount > 0) return
        connectJob?.cancel()
        connectJob = null
        drain()
        runCatching { context.unregisterReceiver(receiver) }
    }

    // ------------------------------------------------------------------ commands

    fun refreshServers() {
        scope.launch {
            val servers = withContext(Dispatchers.IO) { ShieldRepository.servers() }
            val selected = withContext(Dispatchers.IO) { ShieldRepository.selectedServer() }
            _state.update {
                it.copy(
                    servers = servers,
                    selectedGuid = selected?.guid ?: it.selectedGuid,
                    selectedTitle = selected?.title ?: it.selectedTitle,
                )
            }
        }
    }

    fun setAutoConnect(enabled: Boolean) {
        ShieldPrefs.setAutoConnect(enabled)
        _state.update { it.copy(autoConnect = enabled) }
    }

    /** Downloads the subscription again without dropping the current connection. */
    fun refreshSubscription() {
        scope.launch {
            _state.update { it.copy(message = context.getString(R.string.shield_loading_subscription)) }
            val result = withContext(Dispatchers.IO) {
                runCatching { ShieldRepository.ensureSubscription(forceRefresh = true) }
            }
            result.onSuccess { count ->
                // A refreshed subscription can contain different servers, so the
                // next connect should race them again instead of reusing the old pick.
                withContext(Dispatchers.IO) { ShieldPrefs.setServerRanked(false) }
                refreshServers()
                _state.update {
                    it.copy(message = context.getString(R.string.shield_subscription_refreshed, count))
                }
            }.onFailure { error ->
                _state.update { it.copy(message = error.message ?: "Ошибка обновления подписки") }
            }
        }
    }

    fun connect(preferredGuid: String? = null) {
        if (connectJob?.isActive == true) return
        connectJob = scope.launch {
            // Wait for the initial "is the tunnel already up?" exchange with the daemon,
            // otherwise this coroutine and attach() would compete for the same events.
            withTimeoutOrNull(2_000) { _state.first { it.initialized } }
            runConnect(preferredGuid)
        }
    }

    fun disconnect() {
        connectJob?.cancel()
        connectJob = null
        scope.launch {
            _state.update { it.copy(status = ShieldStatus.Disconnecting, message = null) }
            stopAndWait()
            _state.update {
                it.copy(
                    status = ShieldStatus.Idle,
                    attempt = 0,
                    totalAttempts = 0,
                    message = null,
                )
            }
        }
    }

    fun reportPermissionDenied() {
        _state.update {
            it.copy(
                status = ShieldStatus.Error,
                message = context.getString(R.string.shield_permission_denied),
            )
        }
    }

    // ------------------------------------------------------------------ internals

    private suspend fun runConnect(preferredGuid: String?) {
        drain()
        _state.update {
            it.copy(
                status = ShieldStatus.Connecting,
                attempt = 0,
                totalAttempts = 0,
                message = context.getString(R.string.shield_loading_subscription),
            )
        }

        val import = withContext(Dispatchers.IO) {
            runCatching { ShieldRepository.ensureSubscription(forceRefresh = false) }
        }
        if (import.isFailure) {
            val reason = import.exceptionOrNull()?.message ?: "Ошибка загрузки подписки"
            LogUtil.e("ShieldVPN", "subscription import failed: $reason")
            _state.update { it.copy(status = ShieldStatus.Error, message = reason) }
            return
        }

        val servers = withContext(Dispatchers.IO) { ShieldRepository.servers() }
        if (servers.isEmpty()) {
            _state.update {
                it.copy(
                    status = ShieldStatus.Error,
                    servers = servers,
                    message = context.getString(R.string.shield_no_servers),
                )
            }
            return
        }

        // First launch (or a freshly refreshed subscription) has no trusted
        // choice yet: race the servers over plain TCP and keep the fastest one
        // instead of blindly taking the first entry of the subscription.
        var preferred = preferredGuid ?: ShieldRepository.selectedGuid()
        if (preferredGuid == null && !ShieldPrefs.isServerRanked()) {
            _state.update { it.copy(message = context.getString(R.string.shield_ranking_servers)) }
            val fastest = withContext(Dispatchers.IO) {
                runCatching { ShieldRepository.selectFastestServer() }.getOrNull()
            }
            if (!fastest.isNullOrBlank()) preferred = fastest
            ShieldPrefs.setServerRanked(true)
            LogUtil.i("ShieldVPN", "first-launch ranking picked: $fastest")
        }

        val order = buildOrder(servers, preferred)
        _state.update { it.copy(servers = servers, totalAttempts = order.size) }

        if (serviceRunning) stopAndWait()

        for ((index, server) in order.withIndex()) {
            _state.update {
                it.copy(
                    status = ShieldStatus.Connecting,
                    attempt = index + 1,
                    selectedGuid = server.guid,
                    selectedTitle = server.title,
                    message = context.getString(R.string.shield_failover_searching),
                )
            }

            withContext(Dispatchers.IO) { ShieldRepository.selectServer(server.guid) }
            LauncherManager.startService(context, server.guid)

            val startEvent = withTimeoutOrNull(ShieldConfig.CONNECT_TIMEOUT_MS) {
                awaitEvent(AppConfig.MSG_STATE_START_SUCCESS, AppConfig.MSG_STATE_START_FAILURE)
            }
            if (startEvent == AppConfig.MSG_STATE_START_SUCCESS && awaitHealthy()) {
                LogUtil.i("ShieldVPN", "connected to ${server.title}")
                _state.update {
                    it.copy(
                        status = ShieldStatus.Connected,
                        selectedGuid = server.guid,
                        selectedTitle = server.title,
                        message = null,
                    )
                }
                return
            }

            LogUtil.w("ShieldVPN", "server ${server.title} failed (event=$startEvent), trying next")
            stopAndWait()
        }

        _state.update {
            it.copy(
                status = ShieldStatus.Error,
                message = "Не удалось подключиться ни к одному серверу",
            )
        }
    }

    private fun buildOrder(servers: List<ShieldServer>, preferredGuid: String?): List<ShieldServer> {
        val index = servers.indexOfFirst { it.guid == preferredGuid }.takeIf { it >= 0 } ?: 0
        val rotated = servers.drop(index) + servers.take(index)
        return rotated.take(ShieldConfig.MAX_FAILOVER_SERVERS)
    }

    private suspend fun awaitHealthy(): Boolean = withContext(Dispatchers.IO) {
        val port = SettingsManager.getSocksPort()
        repeat(ShieldConfig.PROBE_ATTEMPTS) { attempt ->
            if (ShieldRepository.probeSocks(port)) return@withContext true
            if (attempt < ShieldConfig.PROBE_ATTEMPTS - 1) {
                delay(ShieldConfig.PROBE_RETRY_DELAY_MS)
            }
        }
        false
    }

    private suspend fun stopAndWait() {
        LauncherManager.stopService(context)
        if (serviceRunning) {
            withTimeoutOrNull(4_000) { awaitEvent(AppConfig.MSG_STATE_STOP_SUCCESS) }
        }
        serviceRunning = false
        delay(ShieldConfig.STOP_GRACE_MS)
        drain()
    }

    private suspend fun awaitEvent(vararg keys: Int): Int {
        while (true) {
            val key = events.receive()
            if (keys.contains(key)) return key
        }
    }

    private fun drain() {
        while (events.tryReceive().isSuccess) {
            // discard stale events from a previous attempt
        }
    }
}
