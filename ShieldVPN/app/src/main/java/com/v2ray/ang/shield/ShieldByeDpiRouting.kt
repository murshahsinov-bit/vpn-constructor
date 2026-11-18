package com.v2ray.ang.shield

import com.v2ray.ang.dto.V2rayConfig

/**
 * Adds the ByeDPI hop to a generated Xray configuration.
 *
 * The rule is inserted first so user rules (including the catch-all) cannot
 * shadow it: YouTube domains go to the local ciadpi SOCKS5 listener, every other
 * domain keeps using the VLESS/Reality outbound that the config already has.
 *
 * `targetStrategy = "UseIPv4"` makes Xray resolve the destination itself and pass an
 * IPv4 address to ciadpi: the static ciadpi build has no `/etc/resolv.conf`, so it
 * cannot resolve names (`resolve: ... not resolved` in its log) and answers 5s
 * timeouts when a domain is forwarded to it. IPv6 addresses are excluded on purpose:
 * Xray could return one that the mobile network cannot reach, which showed up as
 * instant SOCKS failures for `i.ytimg.com`. The TLS ClientHello (and therefore the
 * blocked SNI) is still produced by the app, so the DPI bypass keeps working.
 */
object ShieldByeDpiRouting {

    fun apply(config: V2rayConfig): Boolean {
        if (!ShieldPrefs.isByeDpiEnabled()) return false

        val tag = ShieldConfig.BYEDPI_OUTBOUND_TAG
        if (config.outbounds.none { it.tag == tag }) {
            val outbound = V2rayConfig.OutboundBean(
                tag = tag,
                protocol = "socks",
                settings = V2rayConfig.OutboundBean.OutSettingsBean(
                    address = ShieldConfig.BYEDPI_HOST,
                    port = ShieldConfig.BYEDPI_PORT,
                ),
                streamSettings = V2rayConfig.OutboundBean.StreamSettingsBean(network = "tcp"),
                mux = null,
                targetStrategy = "UseIPv4",
            )
            config.outbounds.add(outbound)
        }

        if (config.routing.rules.any { it.outboundTag == tag }) return true

        config.routing.rules.add(
            0,
            V2rayConfig.RoutingBean.RulesBean(
                domain = ArrayList(ShieldConfig.BYEDPI_DOMAINS),
                outboundTag = tag,
                network = "tcp",
            ),
        )
        return true
    }
}
