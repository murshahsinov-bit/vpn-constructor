package com.v2ray.ang.shield

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class ShieldLicenseTest {

    private val token = "SVS1.eyJ2IjoxLCJleHAiOjE3OTk5OTk5OTl9.c2lnbmF0dXJl"

    @Test
    fun extractsTokenFromEveryLinkShape() {
        val link = "https://vpn-auth.de1.netrun.io/activate/$token"
        val deepLink = "shieldvpn://activate?token=$token"
        val message = "Ваша ссылка: $link — сохраните её"

        assertEquals(token, ShieldLicense.extractToken(link))
        assertEquals(token, ShieldLicense.extractToken(deepLink))
        assertEquals(token, ShieldLicense.extractToken(message))
        assertEquals(token, ShieldLicense.extractToken("  $token  "))
    }

    @Test
    fun rejectsInputWithoutToken() {
        assertTrue(ShieldLicense.extractToken("").isEmpty())
        assertTrue(ShieldLicense.extractToken("https://example.test/activate/nope").isEmpty())
        assertTrue(ShieldLicense.extractToken("SVS1.broken").isEmpty())
    }

    @Test
    fun daysLeftRoundsUpAndExpires() {
        val now = System.currentTimeMillis() / 1000L
        val active = ShieldLicenseInfo(token, "trial", "android", now + 3 * 86_400 - 60, true)
        val expired = ShieldLicenseInfo(token, "m1", "android", now - 1, false)

        assertEquals(3, active.daysLeft)
        assertTrue(active.isActive)
        assertEquals(0, expired.daysLeft)
        assertFalse(expired.isActive)
    }

    @Test
    fun planTitlesCoverKnownPlans() {
        val now = System.currentTimeMillis() / 1000L
        fun info(plan: String) = ShieldLicenseInfo(token, plan, "android", now + 86_400, false)

        assertEquals("Пробный период", info(ShieldLicense.PLAN_TRIAL).planTitle())
        assertEquals("1 месяц", info("m1").planTitle())
        assertEquals("3 месяца", info("m3").planTitle())
        assertEquals("12 месяцев", info("m12").planTitle())
        assertEquals("Подписка", info("unknown").planTitle())
    }
}
