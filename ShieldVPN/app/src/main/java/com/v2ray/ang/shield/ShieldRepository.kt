package com.v2ray.ang.shield

import com.v2ray.ang.AngApplication
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
import java.security.SecureRandom
import java.security.cert.X509Certificate
import java.util.concurrent.Callable
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import javax.net.ssl.SNIHostName
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLSocket
import javax.net.ssl.X509TrustManager

/** One row of the server picker. */
data class ShieldServer(
    val guid: String,
    val title: String,
    val subtitle: String,
    /** Country emoji extracted from the subscription title, "🌐" when unknown. */
    val flag: String = "🌐",
    /** Last measured latency in milliseconds, null while it has not been probed. */
    val pingMs: Long? = null,
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
     * Makes sure the per-account subscription exists and its profiles are imported.
     *
     * @param forceRefresh re-download even when profiles are already stored.
     * @return number of profiles available for the subscription.
     */
    @Synchronized
    fun ensureSubscription(forceRefresh: Boolean = false): Int {
        // Xray cannot start without the geo databases, so unpack them before any
        // core launch. Cheap: they are only copied on the very first run.
        ShieldGeoAssets.ensure(AngApplication.application)

        // The panel is asked for the signed-in account only. There is deliberately
        // no shared fallback token: without an account there is nothing to fetch.
        val account = ShieldPrefs.subscriptionUser()
            ?: error("Войдите в аккаунт, чтобы загрузить подписку")
        val subscriptionUrl = ShieldConfig.subscriptionUrl(account)
            .ifBlank { error("Не удалось построить адрес подписки") }

        val stored = MmkvManager.decodeSubscription(ShieldConfig.SUBSCRIPTION_ID)
        val created = stored == null
        val urlChanged = stored?.url != subscriptionUrl
        if (created || urlChanged) {
            MmkvManager.encodeSubscription(
                ShieldConfig.SUBSCRIPTION_ID,
                (stored ?: SubscriptionItem()).apply {
                    remarks = ShieldConfig.SUBSCRIPTION_TITLE
                    url = subscriptionUrl
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
        val ageMs = System.currentTimeMillis() - cache.subscription.lastUpdated
        val stale = cache.subscription.lastUpdated <= 0L ||
            ageMs >= TimeUnit.MINUTES.toMillis(ShieldConfig.SUBSCRIPTION_MAX_AGE_MINUTES)

        if (forceRefresh || created || urlChanged || imported.isEmpty() || stale) {
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
        val rawTitle = profile.remarks.ifBlank { "Сервер" }
        val title = stripLeadingDecorations(rawTitle).trim().ifBlank { rawTitle }
        ShieldServer(
            guid = guid,
            title = title,
            subtitle = describe(profile),
            flag = firstFlag(rawTitle) ?: "🌐",
        )
    }

    /**
     * Country flag of a remark as an emoji string, or null when it has none.
     *
     * Implemented by scanning code points instead of a regex: the flag is a pair of
     * regional indicators in the supplementary plane, and Android's ICU regex engine
     * does not reliably match lone surrogate escapes such as `\uD83C`.
     */
    private fun firstFlag(text: String): String? {
        val codePoints = text.codePoints().toArray()
        for (index in 0 until codePoints.size - 1) {
            val first = codePoints[index]
            val second = codePoints[index + 1]
            if (first in REGIONAL_FIRST..REGIONAL_LAST && second in REGIONAL_FIRST..REGIONAL_LAST) {
                return String(Character.toChars(first)) + String(Character.toChars(second))
            }
        }
        return null
    }

    /**
     * Removes the decorative prefix that subscription authors put in front of the
     * name: country flags, the globe/white-flag emoji, and the separators between
     * them ("🇩🇪 | 🌐 | Berlin" becomes "Berlin"). Text without such a prefix is
     * returned unchanged, so plain remarks keep working.
     */
    private fun stripLeadingDecorations(text: String): String {
        var index = 0
        while (index < text.length) {
            val codePoint = text.codePointAt(index)
            val decoration = codePoint in REGIONAL_FIRST..REGIONAL_LAST ||
                codePoint == GLOBE ||
                codePoint == WHITE_FLAG ||
                codePoint == VARIATION_SELECTOR
            if (decoration) {
                index += Character.charCount(codePoint)
                continue
            }
            val char = text[index]
            if (char.isWhitespace() || char in DECORATION_SEPARATORS) {
                index++
                continue
            }
            break
        }
        return text.substring(index)
    }

    private const val REGIONAL_FIRST = 0x1F1E6
    private const val REGIONAL_LAST = 0x1F1FF
    private const val GLOBE = 0x1F310
    private const val WHITE_FLAG = 0x1F3F3
    private const val VARIATION_SELECTOR = 0xFE0F
    private const val DECORATION_SEPARATORS = "|•·/-:"


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
                MmkvManager.decodeServerConfig(guid)?.let { guid to it }
            }
            .toList()
        if (candidates.isEmpty()) return emptyList()

        val pool = Executors.newFixedThreadPool(
            minOf(candidates.size, parallelism.coerceAtLeast(1)),
        )
        return try {
            val futures = candidates.map { (guid, profile) ->
                pool.submit(Callable { ServerLatency(guid, measureReachability(profile, timeoutMs)) })
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

    /**
     * Cheap reachability probe used before the daemon is started.
     *
     * For Reality/TLS nodes it performs a real TLS handshake with the node's SNI:
     * DPI-blocked endpoints accept the TCP connection and then hang, so a plain
     * connect check cannot tell them apart. Nodes without transport security fall
     * back to a TCP connect.
     */
    private fun measureReachability(profile: ProfileItem, timeoutMs: Int): Long {
        val host = profile.server?.trim().orEmpty()
        val port = profile.serverPort?.trim()?.toIntOrNull() ?: return Long.MAX_VALUE
        if (host.isBlank() || port !in 1..65_535) return Long.MAX_VALUE

        val security = profile.security?.trim()?.lowercase().orEmpty()
        if (security != "reality" && security != "tls") {
            return measureTcp(host, port, timeoutMs)
        }
        val serverName = sequenceOf(profile.sni, profile.host, host)
            .mapNotNull { it?.trim()?.takeIf(String::isNotBlank) }
            .firstOrNull()
            ?: return measureTcp(host, port, timeoutMs)
        return try {
            measureTls(host, port, serverName, timeoutMs)
        } catch (e: IllegalArgumentException) {
            // SNI is not a valid hostname (IP literal or strange token): TLS probe
            // cannot help, fall back to a plain connect.
            measureTcp(host, port, timeoutMs)
        }
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
     * TLS ClientHello against the node with its own SNI.
     *
     * Reality serves the impersonated site's certificate, so the handshake only
     * completes when the connection actually reaches the node. Certificate
     * validation is intentionally disabled: the probe measures reachability, not
     * trust (the node's identity is verified by Xray's Reality key later).
     */
    private fun measureTls(host: String, port: Int, serverName: String, timeoutMs: Int): Long {
        val sni = SNIHostName(serverName)
        val started = System.nanoTime()
        val context = SSLContext.getInstance("TLS")
        context.init(null, arrayOf(TRUST_ALL), SecureRandom())
        Socket().use { plain ->
            plain.tcpNoDelay = true
            plain.connect(InetSocketAddress(host, port), timeoutMs)
            plain.soTimeout = timeoutMs
            context.socketFactory.createSocket(plain, serverName, port, true).use { socket ->
                val tls = socket as SSLSocket
                tls.sslParameters = tls.sslParameters.apply { serverNames = listOf(sni) }
                tls.startHandshake()
            }
        }
        return (System.nanoTime() - started) / 1_000_000L
    }

    private val TRUST_ALL = object : X509TrustManager {
        override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) = Unit
        override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) = Unit
        override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
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

                // Consume BND.ADDR / BND.PORT so the socket is in a clean state.
                val consumed = when (head[3].toInt()) {
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
                if (!consumed) return false

                // A CONNECT alone does not prove the tunnel carries traffic: dead
                // nodes accept it and then drop the payload. Request a tiny page
                // through the tunnel and require a real HTTP response.
                val httpRequest = (
                    "GET ${ShieldConfig.HEALTH_PATH} HTTP/1.1\r\n" +
                        "Host: ${ShieldConfig.HEALTH_HOST}\r\n" +
                        "User-Agent: ShieldVPN\r\n" +
                        "Connection: close\r\n\r\n"
                    ).toByteArray(Charsets.US_ASCII)
                output.write(httpRequest)
                output.flush()

                val response = ByteArray(5)
                readFully(input, response) &&
                    response.contentEquals("HTTP/".toByteArray(Charsets.US_ASCII))
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
