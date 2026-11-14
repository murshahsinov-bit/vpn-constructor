package com.v2ray.ang.shield

/**
 * Single source of truth for everything that is specific to this branded build.
 *
 * The subscription URL below is baked into the APK: the user never has to paste a
 * link or scan a QR code. Change [SUBSCRIPTION_URL] here and rebuild to point the
 * app at another panel.
 */
object ShieldConfig {

    /** Panel subscription that is imported automatically on the very first launch. */
    const val SUBSCRIPTION_URL =
        "https://vpn-auth.de1.netrun.io/sub/auto_happ.txt?token=210c785aac0ae869b3fb35ebd8d8727e"

    /** Fixed MMKV key so re-launches update the same subscription instead of adding new ones. */
    const val SUBSCRIPTION_ID = "shield_default_subscription"

    const val SUBSCRIPTION_TITLE = "ShieldVPN"

    /** Refresh the subscription in the background every 6 hours. */
    const val SUBSCRIPTION_UPDATE_INTERVAL_MINUTES = 360L

    /** MMKV preference keys. */
    const val PREF_BOOTSTRAPPED = "shield_bootstrapped"
    const val PREF_AUTO_CONNECT = "shield_auto_connect"

    /** Set once the first-launch latency race has picked a server. */
    const val PREF_SERVER_RANKED = "shield_server_ranked"

    /** Endpoint used by the SOCKS5 health probe (only a TCP CONNECT, no payload). */
    const val HEALTH_HOST = "www.gstatic.com"
    const val HEALTH_PORT = 443

    /** How long the daemon may take to report MSG_STATE_START_SUCCESS. */
    const val CONNECT_TIMEOUT_MS = 25_000L

    /** Health probe tuning. */
    const val PROBE_TIMEOUT_MS = 6_000
    const val PROBE_ATTEMPTS = 3
    const val PROBE_RETRY_DELAY_MS = 1_200L

    /** Stop after this many servers so a broken subscription cannot loop forever. */
    const val MAX_FAILOVER_SERVERS = 8

    /** Grace period after a stop request before the next server is started. */
    const val STOP_GRACE_MS = 500L

    /**
     * First-launch latency race: how many subscription servers to probe, how many
     * connect attempts to run in parallel, and the per-attempt TCP timeout.
     *
     * The ranking is a plain TCP connect to address:port. It is cheap, does not
     * touch the tunnel, and correlates well with the handshake time of the real
     * VLESS/Reality connection.
     */
    const val LATENCY_PROBE_COUNT = 24
    const val LATENCY_PARALLELISM = 12
    const val LATENCY_PROBE_TIMEOUT_MS = 2_500
}
