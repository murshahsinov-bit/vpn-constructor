package com.v2ray.ang.shield

import com.v2ray.ang.dto.entities.ProfileItem
import com.v2ray.ang.dto.entities.SubscriptionItem
import com.v2ray.ang.handler.AngConfigManager
import com.v2ray.ang.handler.MmkvManager
import com.v2ray.ang.handler.SubscriptionUpdater
import com.v2ray.ang.util.LogUtil
import java.io.InputStream
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.Socket
import java.util.concurrent.Callable
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** One row of the server picker. */
data class ShieldServer(
    val guid: String,
    val title: String,
    val subtitle: String,
)

/**
 * All storage / network work for the branded client.
 *
 * Every function here blocks (MMKV, HTTP, sockets), so callers must run them on
 * [kotlinx.coroutines.Dispatchers.IO].
 */
object ShieldRepository {

    private const val TAG = "ShieldVPN"

    /** Xray's SOCKS inbound binds IPv4 loopback only. */
    private const val LOOPBACK_HOST = "127.0.0.1"

    /**
     * Makes sure the baked-in subscription exists and its profiles are imported.
     *
     * @param forceRefresh re-download even when profiles are already stored.
     * @return number of profiles available for the subscription.
     */
    @Synchronized
    fun ensureSubscription(forceRefresh: Boolean = false): Int {
        val stored = MmkvManager.decodeSubscription(ShieldConfig.SUBSCRIPTION_ID)
        val created = stored == null
        val urlChanged = stored != null && stored.url != ShieldConfig.SUBSCRIPTION_URL
        if (created || urlChanged) {
            MmkvManager.encodeSubscription(
                ShieldConfig.SUBSCRIPTION_ID,
                (stored ?: SubscriptionItem()).apply {
                    remarks = ShieldConfig.SUBSCRIPTION_TITLE
                    url = ShieldConfig.SUBSCRIPTION_URL
                    enabled = true
                    autoUpdate = true
                    updateInterval = ShieldConfig.SUBSCRIPTION_UPDATE_INTERVAL_MINUTES
                },
            )
        }

        val cache = MmkvManager.decodeSubscriptions()
            .firstOrNull { it.guid == ShieldConfig.SUBSCRIPTION_ID }
            ?: error("Подписка ShieldVPN не создана")

        val imported = MmkvManager.decodeServerList(ShieldConfig.SUBSCRIPTION_ID)
        val neverDownloaded = cache.subscription.lastUpdated <= 0L

        if (forceRefresh || created || urlChanged || imported.isEmpty() || neverDownloaded) {
            val result = AngConfigManager.updateConfigViaSub(cache)
            LogUtil.i(
                TAG,
                "subscription sync: configs=${result.configCount} ok=${result.successCount} " +
                    "fail=${result.failureCount}",
            )
            if (result.configCount <= 0 && imported.isEmpty()) {
                error("Не удалось загрузить подписку. Проверьте интернет.")
            }
        }

        // Keep the periodic updater in sync with the subscription we just (re)created.
        runCatching { SubscriptionUpdater.syncOne(subId = ShieldConfig.SUBSCRIPTION_ID) }
            .onFailure { LogUtil.e(TAG, "failed to schedule subscription update", it) }

        ShieldPrefs.setBootstrapped(true)
        return MmkvManager.decodeServerList(ShieldConfig.SUBSCRIPTION_ID).size
    }

    /** GUIDs belonging to the built-in subscription, falling back to everything stored. */
    fun serverGuids(): List<String> {
        val own = MmkvManager.decodeServerList(ShieldConfig.SUBSCRIPTION_ID)
        return if (own.isNotEmpty()) own else MmkvManager.decodeAllServerList()
    }

    /** Profiles ready to be rendered by the UI. */
    fun servers(): List<ShieldServer> = serverGuids().mapNotNull { guid ->
        val profile = MmkvManager.decodeServerConfig(guid) ?: return@mapNotNull null
        ShieldServer(
            guid = guid,
            title = profile.remarks.ifBlank { "Сервер" },
            subtitle = describe(profile),
        )
    }

    fun profile(guid: String): ProfileItem? = MmkvManager.decodeServerConfig(guid)

    fun selectedGuid(): String? = MmkvManager.getSelectServer()

    /** Selects the first server when nothing valid is selected yet. */
    fun ensureServerSelected(): String? {
        val guids = serverGuids()
        if (guids.isEmpty()) return null
        val current = selectedGuid()
        if (current != null && guids.contains(current)) return current
        val first = guids.first()
        MmkvManager.setSelectServer(first)
        return first
    }

    fun selectServer(guid: String) {
        MmkvManager.setSelectServer(guid)
    }

    fun selectedServer(): ShieldServer? {
        val guid = selectedGuid() ?: return null
        return servers().firstOrNull { it.guid == guid }
    }

    /** One entry of the first-launch latency race. */
    data class ServerLatency(val guid: String, val delayMs: Long)

    /**
     * Races a plain TCP connect to every server's address:port in parallel and
     * returns the GUIDs sorted by connect time.
     *
     * Unreachable servers get [Long.MAX_VALUE] and therefore sink to the end,
     * but stay in the list so the failover loop can still try them.
     */
    fun rankServersByLatency(
        limit: Int = ShieldConfig.LATENCY_PROBE_COUNT,
        parallelism: Int = ShieldConfig.LATENCY_PARALLELISM,
        timeoutMs: Int = ShieldConfig.LATENCY_PROBE_TIMEOUT_MS,
    ): List<ServerLatency> {
        val candidates = serverGuids().asSequence()
            .take(limit)
            .mapNotNull { guid ->
                val profile = MmkvManager.decodeServerConfig(guid) ?: return@mapNotNull null
                val host = profile.server?.trim().orEmpty()
                val port = profile.serverPort?.trim()?.toIntOrNull() ?: return@mapNotNull null
                if (host.isBlank() || port !in 1..65_535) return@mapNotNull null
                Triple(guid, host, port)
            }
            .toList()
        if (candidates.isEmpty()) return emptyList()

        val pool = Executors.newFixedThreadPool(
            minOf(candidates.size, parallelism.coerceAtLeast(1)),
        )
        return try {
            val futures = candidates.map { (guid, host, port) ->
                pool.submit(Callable { ServerLatency(guid, measureTcp(host, port, timeoutMs)) })
            }
            futures.mapNotNull { future ->
                runCatching {
                    future.get(timeoutMs + 1_500L, TimeUnit.MILLISECONDS)
                }.getOrNull()
            }.sortedBy { it.delayMs }
        } finally {
            pool.shutdownNow()
        }
    }

    /** Picks and stores the fastest reachable server. Returns its GUID. */
    fun selectFastestServer(): String? {
        val ranked = rankServersByLatency()
        val best = ranked.firstOrNull { it.delayMs != Long.MAX_VALUE } ?: ranked.firstOrNull()
        if (best != null) selectServer(best.guid)
        return best?.guid
    }

    private fun measureTcp(host: String, port: Int, timeoutMs: Int): Long = try {
        val started = System.nanoTime()
        Socket().use { socket ->
            socket.tcpNoDelay = true
            socket.connect(InetSocketAddress(host, port), timeoutMs)
        }
        (System.nanoTime() - started) / 1_000_000L
    } catch (e: Exception) {
        LogUtil.d(TAG, "latency probe $host:$port failed: ${e.message}")
        Long.MAX_VALUE
    }

    /**
     * End-to-end liveness check.
     *
     * Opens a SOCKS5 CONNECT through the local Xray inbound to [ShieldConfig.HEALTH_HOST].
     * A successful CONNECT means the VLESS/Reality/XHTTP handshake with the remote server
     * worked and the outbound really carries traffic.
     */
    fun probeSocks(socksPort: Int, timeoutMs: Int = ShieldConfig.PROBE_TIMEOUT_MS): Boolean {
        if (socksPort <= 0) return false
        return try {
            Socket().use { socket ->
                // 127.0.0.1, not "localhost"/loopback family: the Xray SOCKS inbound listens on IPv4 loopback.
                socket.connect(InetSocketAddress(InetAddress.getByName(LOOPBACK_HOST), socksPort), timeoutMs)
                socket.soTimeout = timeoutMs
                val output = socket.getOutputStream()
                val input = socket.getInputStream()

                // Greeting: SOCKS5, one method, "no auth".
                output.write(byteArrayOf(0x05, 0x01, 0x00))
                output.flush()
                val greeting = ByteArray(2)
                if (!readFully(input, greeting)) return false
                if (greeting[0] != 0x05.toByte() || greeting[1] != 0x00.toByte()) return false

                // CONNECT to the probe host using a domain-name address.
                val host = ShieldConfig.HEALTH_HOST.toByteArray(Charsets.US_ASCII)
                val request = byteArrayOf(0x05, 0x01, 0x00, 0x03, host.size.toByte()) + host +
                    byteArrayOf(
                        (ShieldConfig.HEALTH_PORT shr 8).toByte(),
                        (ShieldConfig.HEALTH_PORT and 0xFF).toByte(),
                    )
                output.write(request)
                output.flush()

                val head = ByteArray(4)
                if (!readFully(input, head)) return false
                if (head[0] != 0x05.toByte() || head[1] != 0x00.toByte()) return false

                // Consume BND.ADDR / BND.PORT so the socket closes cleanly.
                when (head[3].toInt()) {
                    0x01 -> readFully(input, ByteArray(4)) && readFully(input, ByteArray(2))
                    0x03 -> {
                        val length = ByteArray(1)
                        readFully(input, length) &&
                            readFully(input, ByteArray(length[0].toInt() and 0xFF)) &&
                            readFully(input, ByteArray(2))
                    }
                    0x04 -> readFully(input, ByteArray(16)) && readFully(input, ByteArray(2))
                    else -> false
                }
            }
        } catch (e: Exception) {
            LogUtil.d(TAG, "probe failed on port $socksPort: ${e.message}")
            false
        }
    }

    private fun describe(profile: ProfileItem): String {
        val address = AngConfigManager.generateDescription(profile)
        val protocol = profile.configType.name
        val transport = profile.network?.takeIf { it.isNotBlank() }?.uppercase()
        return listOfNotNull(protocol, transport, address.ifBlank { null })
            .joinToString(" · ")
    }

    private fun readFully(input: InputStream, buffer: ByteArray): Boolean {
        var offset = 0
        while (offset < buffer.size) {
            val read = input.read(buffer, offset, buffer.size - offset)
            if (read < 0) return false
            offset += read
        }
        return true
    }
}
