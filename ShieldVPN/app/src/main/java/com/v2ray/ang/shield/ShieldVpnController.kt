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
    /** True while the latency race is running in the background. */
    val pinging: Boolean = false,
    /** GUID -> latency in ms, [Long.MAX_VALUE] when the node is unreachable. */
    val pings: Map<String, Long> = emptyMap(),
    /** "Авто" mode: the app always dials the fastest reachable server itself. */
    val autoMode: Boolean = true,
    /** Local ByeDPI bypass for the YouTube domains. */
    val byeDpiEnabled: Boolean = true,
    /** True when the ciadpi listener is actually up. */
    val byeDpiRunning: Boolean = false,
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

    private val _state = MutableStateFlow(
        ShieldUiState(
            autoConnect = ShieldPrefs.isAutoConnect(),
            byeDpiEnabled = ShieldPrefs.isByeDpiEnabled(),
        )
    )
    val state: StateFlow<ShieldUiState> = _state.asStateFlow()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val events = Channel<Int>(Channel.UNLIMITED)

    private var attachCount = 0
    private var connectJob: Job? = null
    private var pingJob: Job? = null
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
                    ensureByeDpi()
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
            // First screen of the app: probe every node so the picker shows real
            // numbers and "Авто" can dial the best one immediately.
            if (servers.isNotEmpty() && _state.value.pings.isEmpty()) pingAll()
        }
    }

    /**
     * Races a TLS/TCP probe against every subscription server and publishes the
     * latencies, sorted fastest-first. Used on launch and by the picker refresh.
     */
    fun pingAll() {
        if (pingJob?.isActive == true) return
        pingJob = scope.launch {
            val servers = withContext(Dispatchers.IO) { ShieldRepository.servers() }
            if (servers.isEmpty()) return@launch
            _state.update { it.copy(pinging = true, servers = servers) }
            val ranked = withContext(Dispatchers.IO) {
                runCatching { ShieldRepository.rankServersByLatency() }.getOrDefault(emptyList())
            }
            val pings = ranked.associate { it.guid to it.delayMs }
            _state.update { current ->
                current.copy(
                    pinging = false,
                    pings = pings,
                    servers = current.servers.sortedBy { server ->
                        pings[server.guid] ?: Long.MAX_VALUE
                    },
                )
            }
        }
    }

    fun setAutoMode(enabled: Boolean) {
        _state.update { it.copy(autoMode = enabled) }
        if (enabled) {
            // Auto always means "the fastest node we currently know about".
            bestKnownGuid()?.let { guid ->
                val server = _state.value.servers.firstOrNull { it.guid == guid }
                _state.update { it.copy(selectedGuid = guid, selectedTitle = server?.title) }
            }
        }
    }

    fun setByeDpiEnabled(enabled: Boolean) {
        ShieldPrefs.setByeDpiEnabled(enabled)
        _state.update { it.copy(byeDpiEnabled = enabled) }
        scope.launch {
            val connected = _state.value.status == ShieldStatus.Connected
            val running = withContext(Dispatchers.IO) {
                when {
                    enabled && connected -> ShieldByeDpi.start(context)
                    enabled -> false
                    else -> {
                        ShieldByeDpi.stop()
                        false
                    }
                }
            }
            _state.update { it.copy(byeDpiRunning = running) }
            // The byedpi rule is baked into the generated Xray config, so a live
            // tunnel has to be rebuilt for the switch to take effect.
            if (connected) {
                val manualGuid = _state.value.selectedGuid.takeIf { !_state.value.autoMode }
                connect(manualGuid)
            }
        }
    }

    /** GUID of the fastest reachable server from the last latency race. */
    private fun bestKnownGuid(): String? {
        val pings = _state.value.pings
        return _state.value.servers
            .mapNotNull { server -> pings[server.guid]?.let { server.guid to it } }
            .filter { it.second != Long.MAX_VALUE }
            .minByOrNull { it.second }
            ?.first
    }

    private fun ensureByeDpi() {
        if (!ShieldPrefs.isByeDpiEnabled()) return
        scope.launch {
            val running = withContext(Dispatchers.IO) { ShieldByeDpi.start(context) }
            _state.update { it.copy(byeDpiRunning = running) }
        }
    }

    fun setAutoConnect(enabled: Boolean) {
        ShieldPrefs.setAutoConnect(enabled)
        _state.update { it.copy(autoConnect = enabled) }
    }

    /**
     * Loads the per-account subscription right after sign-in so the server picker
     * is populated even when auto-connect is off. Uses the cached copy when it is
     * still fresh, so this is cheap on every launch.
     */
    fun ensureSubscription() {
        scope.launch {
            withContext(Dispatchers.IO) {
                runCatching { ShieldRepository.ensureSubscription(forceRefresh = false) }
                    .onFailure { LogUtil.w("ShieldVPN", "subscription prefetch failed: ${it.message}") }
            }
            refreshServers()
        }
    }

    /** Downloads the subscription again without dropping the current connection. */
    fun refreshSubscription() {        scope.launch {
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
        if (preferredGuid != null) {
            _state.update {
                it.copy(
                    autoMode = false,
                    selectedGuid = preferredGuid,
                    selectedTitle = it.servers.firstOrNull { server -> server.guid == preferredGuid }?.title,
                )
            }
        } else {
            _state.update { it.copy(autoMode = true) }
        }
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
            withContext(Dispatchers.IO) { ShieldByeDpi.stop() }
            _state.update {
                it.copy(
                    status = ShieldStatus.Idle,
                    attempt = 0,
                    totalAttempts = 0,
                    message = null,
                    byeDpiRunning = false,
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

        var preferred = preferredGuid ?: ShieldRepository.selectedGuid()
        var lastError: String? = null

        // The local DPI bypass must be listening before Xray loads a config that
        // routes the YouTube domains into it.
        val byeDpiRunning = withContext(Dispatchers.IO) {
            if (ShieldPrefs.isByeDpiEnabled()) ShieldByeDpi.start(context) else false
        }
        _state.update { it.copy(byeDpiRunning = byeDpiRunning) }

        for (round in 0 until ShieldConfig.CONNECT_ROUNDS) {
            val forceRefresh = round > 0
            val import = withContext(Dispatchers.IO) {
                runCatching { ShieldRepository.ensureSubscription(forceRefresh = forceRefresh) }
            }
            if (import.isFailure) {
                val reason = import.exceptionOrNull()?.message ?: "Ошибка загрузки подписки"
                LogUtil.e("ShieldVPN", "subscription import failed (round $round): $reason")
                lastError = reason
                if (round > 0) break
            }

            val servers = withContext(Dispatchers.IO) { ShieldRepository.servers() }
            if (servers.isEmpty()) {
                LogUtil.w("ShieldVPN", "subscription has no servers (round $round)")
                if (round > 0) break
                _state.update {
                    it.copy(
                        status = ShieldStatus.Error,
                        servers = servers,
                        message = context.getString(R.string.shield_no_servers),
                    )
                }
                return
            }

            // Always race the servers before dialing: free nodes die fast and the
            // stored pick may already be blocked by DPI. The TLS probe drops
            // endpoints that accept TCP but never complete a handshake.
            _state.update {
                it.copy(servers = servers, message = context.getString(R.string.shield_ranking_servers))
            }
            val ranked = withContext(Dispatchers.IO) {
                runCatching { ShieldRepository.rankServersByLatency() }.getOrDefault(emptyList())
            }
            val pings = ranked.associate { it.guid to it.delayMs }
            _state.update { it.copy(pings = pings) }
            val reachable = ranked.filter { it.delayMs != Long.MAX_VALUE }.map { it.guid }
            LogUtil.i(
                "ShieldVPN",
                "round $round: ${reachable.size}/${servers.size} servers reachable",
            )
            if (preferred.isNullOrBlank() || servers.none { it.guid == preferred }) {
                preferred = reachable.firstOrNull()
            }

            val order = buildOrder(servers, preferred, reachable)
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

                var connected = false
                try {
                    withContext(Dispatchers.IO) { ShieldRepository.selectServer(server.guid) }
                    LauncherManager.startService(context, server.guid)

                    val startEvent = withTimeoutOrNull(ShieldConfig.CONNECT_TIMEOUT_MS) {
                        awaitEvent(AppConfig.MSG_STATE_START_SUCCESS, AppConfig.MSG_STATE_START_FAILURE)
                    }
                    if (startEvent == AppConfig.MSG_STATE_START_SUCCESS && awaitHealthy()) {
                        connected = true
                        ShieldPrefs.setServerRanked(true)
                        LogUtil.i("ShieldVPN", "connected to ${server.title}")
                        _state.update {
                            it.copy(
                                status = ShieldStatus.Connected,
                                selectedGuid = server.guid,
                                selectedTitle = server.title,
                                message = null,
                            )
                        }
                    } else {
                        LogUtil.w(
                            "ShieldVPN",
                            "server ${server.title} failed (event=$startEvent), trying next",
                        )
                    }
                } catch (t: Throwable) {
                    // A crash of the :daemon process must not take down the UI
                    // coroutine: report it and keep failing over.
                    LogUtil.e("ShieldVPN", "attempt for ${server.title} crashed: ${t.message}", t)
                    lastError = t.message
                } finally {
                    if (!connected) {
                        runCatching { stopAndWait() }
                    }
                }
                if (connected) return
            }

            if (round == 0) {
                LogUtil.w("ShieldVPN", "all servers failed, refreshing subscription and retrying")
            }
        }

        _state.update {
            it.copy(
                status = ShieldStatus.Error,
                message = lastError ?: "Не удалось подключиться ни к одному серверу",
            )
        }
    }

    /**
     * Builds the failover order: reachable servers first (starting from the
     * preferred/pinned one), then a few unreachable ones only when the probe found
     * almost nothing, so a broken probe cannot leave the app with no attempts.
     */
    private fun buildOrder(
        servers: List<ShieldServer>,
        preferredGuid: String?,
        reachable: List<String>,
    ): List<ShieldServer> {
        val byGuid = servers.associateBy { it.guid }
        val ordered = LinkedHashMap<String, ShieldServer>()

        val reachableServers = reachable.mapNotNull { byGuid[it] }
        val start = reachableServers.indexOfFirst { it.guid == preferredGuid }.takeIf { it >= 0 } ?: 0
        (reachableServers.drop(start) + reachableServers.take(start)).forEach {
            ordered[it.guid] = it
        }

        val fallbackSlots = when {
            reachableServers.isEmpty() -> ShieldConfig.MAX_FAILOVER_SERVERS
            reachableServers.size < 3 -> 3 - reachableServers.size
            else -> 0
        }
        if (fallbackSlots > 0) {
            val index = servers.indexOfFirst { it.guid == preferredGuid }.takeIf { it >= 0 } ?: 0
            var added = 0
            for (server in servers.drop(index) + servers.take(index)) {
                if (added >= fallbackSlots) break
                if (ordered.containsKey(server.guid)) continue
                ordered[server.guid] = server
                added++
            }
        }

        return ordered.values.take(ShieldConfig.MAX_FAILOVER_SERVERS)
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
