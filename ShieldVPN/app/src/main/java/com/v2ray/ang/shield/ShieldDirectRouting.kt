package com.v2ray.ang.shield

import com.v2ray.ang.AppConfig
import com.v2ray.ang.dto.V2rayConfig

/**
 * Keeps the subscription panel off the tunnel.
 *
 * The account subscription is usually refreshed while the system VPN is already
 * up. Every app socket then enters Xray through the tun inbound, and the default
 * rule set sends it to the proxy outbound: the panel is reached from the node
 * address instead of the phone, closes the TLS handshake, and "Обновить
 * подписку" fails exactly when the tunnel is connected. A first rule sends the
 * panel host to the direct outbound, so the refresh always uses the underlying
 * network.
 *
 * The rule is prepended, so neither the catch-all nor a user rule can shadow it.
 */
object ShieldDirectRouting {

    /** Xray domain matcher for the panel host (`domain:` also covers subdomains). */
    private val PANEL_DOMAIN = "domain:${ShieldConfig.SUBSCRIPTION_HOST}"

    fun apply(config: V2rayConfig): Boolean {
        val alreadyRouted = config.routing.rules.any { rule ->
            rule.outboundTag == AppConfig.TAG_DIRECT && rule.domain?.contains(PANEL_DOMAIN) == true
        }
        if (alreadyRouted) return false

        if (config.outbounds.none { it.tag == AppConfig.TAG_DIRECT }) {
            config.outbounds.add(
                V2rayConfig.OutboundBean(
                    tag = AppConfig.TAG_DIRECT,
                    protocol = "freedom",
                    settings = V2rayConfig.OutboundBean.OutSettingsBean(),
                    streamSettings = null,
                    mux = null,
                ),
            )
        }

        config.routing.rules.add(
            0,
            V2rayConfig.RoutingBean.RulesBean(
                domain = arrayListOf(PANEL_DOMAIN),
                outboundTag = AppConfig.TAG_DIRECT,
                network = "tcp,udp",
            ),
        )
        return true
    }
}
