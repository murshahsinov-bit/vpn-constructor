package com.v2ray.ang.shield

import com.v2ray.ang.AppConfig
import com.v2ray.ang.dto.V2rayConfig
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class ShieldDirectRoutingTest {

    private val panelDomain = "domain:${ShieldConfig.SUBSCRIPTION_HOST}"

    @Test
    fun `adds a direct rule before existing rules`() {
        val config = configWith(outboundTags = listOf(AppConfig.TAG_PROXY, AppConfig.TAG_DIRECT))
        config.routing.rules.add(
            V2rayConfig.RoutingBean.RulesBean(network = "tcp,udp", outboundTag = AppConfig.TAG_PROXY),
        )

        assertTrue(ShieldDirectRouting.apply(config))

        assertEquals(2, config.routing.rules.size)
        val rule = config.routing.rules.first()
        assertEquals(listOf(panelDomain), rule.domain)
        assertEquals(AppConfig.TAG_DIRECT, rule.outboundTag)
        assertEquals("tcp,udp", rule.network)
        // The previously configured catch-all is still there, after the new rule.
        assertEquals(AppConfig.TAG_PROXY, config.routing.rules[1].outboundTag)
    }

    @Test
    fun `creates the direct outbound when the profile has none`() {
        val config = configWith(outboundTags = listOf(AppConfig.TAG_PROXY))

        assertTrue(ShieldDirectRouting.apply(config))

        val direct = config.outbounds.single { it.tag == AppConfig.TAG_DIRECT }
        assertEquals("freedom", direct.protocol)
    }

    @Test
    fun `reuses an existing direct outbound`() {
        val config = configWith(outboundTags = listOf(AppConfig.TAG_PROXY, AppConfig.TAG_DIRECT))

        assertTrue(ShieldDirectRouting.apply(config))

        assertEquals(2, config.outbounds.size)
        assertEquals(1, config.outbounds.count { it.tag == AppConfig.TAG_DIRECT })
    }

    @Test
    fun `does not duplicate the rule on a second config build`() {
        val config = configWith(outboundTags = listOf(AppConfig.TAG_PROXY, AppConfig.TAG_DIRECT))

        assertTrue(ShieldDirectRouting.apply(config))
        assertFalse(ShieldDirectRouting.apply(config))

        assertEquals(1, config.routing.rules.count { it.outboundTag == AppConfig.TAG_DIRECT })
    }

    @Test
    fun `leaves a rule that already sends the panel direct untouched`() {
        val config = configWith(outboundTags = listOf(AppConfig.TAG_PROXY, AppConfig.TAG_DIRECT))
        config.routing.rules.add(
            V2rayConfig.RoutingBean.RulesBean(
                domain = arrayListOf(panelDomain),
                outboundTag = AppConfig.TAG_DIRECT,
            ),
        )

        assertFalse(ShieldDirectRouting.apply(config))

        assertEquals(1, config.routing.rules.size)
    }

    private fun configWith(outboundTags: List<String>): V2rayConfig = V2rayConfig(
        log = V2rayConfig.LogBean(),
        inbounds = arrayListOf(),
        outbounds = outboundTags.mapTo(arrayListOf()) { tag ->
            V2rayConfig.OutboundBean(tag = tag, protocol = "freedom")
        },
        routing = V2rayConfig.RoutingBean(
            domainStrategy = "AsIs",
            rules = arrayListOf(),
        ),
    )
}
