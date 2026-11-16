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

    /** Token part of [SUBSCRIPTION_URL], mirrored to the user's Firebase profile. */
    fun subscriptionToken(): String =
        Regex("[?&]token=([A-Za-z0-9]+)")
            .find(SUBSCRIPTION_URL)
            ?.groupValues
            ?.getOrNull(1)
            .orEmpty()

    const val SUBSCRIPTION_TITLE = "ShieldVPN"

    /**
     * Free nodes die fast: re-download the subscription whenever the cached copy
     * is older than this. The aggregator refreshes the panel every hour.
     */
    const val SUBSCRIPTION_MAX_AGE_MINUTES = 15L

    /** Refresh the subscription in the background every 6 hours. */
    const val SUBSCRIPTION_UPDATE_INTERVAL_MINUTES = 360L

    /** MMKV preference keys. */
    const val PREF_BOOTSTRAPPED = "shield_bootstrapped"
    const val PREF_AUTO_CONNECT = "shield_auto_connect"

    /** Set once the first-launch latency race has picked a server. */
    const val PREF_SERVER_RANKED = "shield_server_ranked"

    // ------------------------------------------------------------------ ByeDPI

    /**
     * Local DPI-bypass proxy (ciadpi from hufrea/byedpi). It runs as a plain
     * userspace process next to the Xray tunnel: the system VPN is still owned by
     * Xray, ByeDPI is only a loopback SOCKS5 endpoint for the domains that the
     * Russian DPI throttles (YouTube).
     */
    const val BYEDPI_HOST = "127.0.0.1"
    const val BYEDPI_PORT = 1080

    /**
     * Default ciadpi strategy. `--disorder 1` splits the first TLS record and
     * `--auto=torst` re-tries the alternative fragmentation modes when a
     * handshake stalls. Verified against YouTube on a Russian mobile network.
     */
    const val BYEDPI_DEFAULT_ARGS = "--disorder 1 --auto=torst --timeout 5"

    /** Xray outbound tag and the domains steered into it. */
    const val BYEDPI_OUTBOUND_TAG = "byedpi"

    val BYEDPI_DOMAINS = listOf(
        "domain:youtube.com",
        "domain:youtu.be",
        "domain:youtube-nocookie.com",
        "domain:googlevideo.com",
        "domain:ytimg.com",
        "domain:ggpht.com",
        "domain:youtubei.googleapis.com",
    )

    const val PREF_BYEDPI_ENABLED = "shield_byedpi_enabled"
    const val PREF_BYEDPI_ARGS = "shield_byedpi_args"

    // ------------------------------------------------------------------- auth

    const val PREF_AUTH_EMAIL = "shield_auth_email"
    const val PREF_AUTH_NAME = "shield_auth_name"
    const val PREF_AUTH_SECRET = "shield_auth_secret"
    const val PREF_AUTH_SIGNED_IN = "shield_auth_signed_in"

    /**
     * Data-plane probe endpoint, requested through the tunnel with a plain HTTP
     * GET. A successful SOCKS CONNECT alone is not enough: dead free nodes accept
     * the TCP handshake and then drop the payload.
     */
    const val HEALTH_HOST = "connectivitycheck.gstatic.com"
    const val HEALTH_PORT = 80
    const val HEALTH_PATH = "/generate_204"

    /** How long the daemon may take to report MSG_STATE_START_SUCCESS. */
    const val CONNECT_TIMEOUT_MS = 12_000L

    /** Health probe tuning (SOCKS CONNECT + HTTP GET through the tunnel). */
    const val PROBE_TIMEOUT_MS = 4_000
    const val PROBE_ATTEMPTS = 2
    const val PROBE_RETRY_DELAY_MS = 900L

    /** Stop after this many servers so a broken subscription cannot loop forever. */
    const val MAX_FAILOVER_SERVERS = 12

    /** Grace period after a stop request before the next server is started. */
    const val STOP_GRACE_MS = 400L

    /**
     * Pre-connect reachability race: how many subscription servers to probe, how
     * many probes to run in parallel, and the per-probe timeout.
     *
     * The probe performs a TLS handshake with the node's own SNI (Reality falls
     * back to the impersonated site), so DPI-blocked nodes are dropped instead of
     * being tried one by one.
     */
    const val LATENCY_PROBE_COUNT = 60
    const val LATENCY_PARALLELISM = 16
    const val LATENCY_PROBE_TIMEOUT_MS = 3_000

    /** How many full rounds (fresh subscription on the second one) connect may run. */
    const val CONNECT_ROUNDS = 2
}
