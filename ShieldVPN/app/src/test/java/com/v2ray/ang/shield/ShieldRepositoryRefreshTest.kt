package com.v2ray.ang.shield

import com.v2ray.ang.dto.SubscriptionUpdateResult
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class ShieldRepositoryRefreshTest {

    @Test
    fun `a downloaded list is never a failure`() {
        val result = SubscriptionUpdateResult(configCount = 3, successCount = 1)

        assertFalse(ShieldRepository.isSubscriptionRefreshFailure(result, hasCachedProfiles = false, strict = false))
        assertFalse(ShieldRepository.isSubscriptionRefreshFailure(result, hasCachedProfiles = true, strict = true))
    }

    @Test
    fun `a refused refresh fails even when the cache has servers`() {
        val refused = SubscriptionUpdateResult(failureCount = 1)

        assertTrue(ShieldRepository.isSubscriptionRefreshFailure(refused, hasCachedProfiles = true, strict = true))
    }

    @Test
    fun `a background sync may fall back to the cache`() {
        val refused = SubscriptionUpdateResult(failureCount = 1)

        assertFalse(ShieldRepository.isSubscriptionRefreshFailure(refused, hasCachedProfiles = true, strict = false))
    }

    @Test
    fun `the first download has nothing to fall back on`() {
        val refused = SubscriptionUpdateResult(failureCount = 1)

        assertTrue(ShieldRepository.isSubscriptionRefreshFailure(refused, hasCachedProfiles = false, strict = false))
    }

    @Test
    fun `an empty profile list counts as a failure`() {
        val empty = SubscriptionUpdateResult(configCount = 0, successCount = 1)

        assertTrue(ShieldRepository.isSubscriptionRefreshFailure(empty, hasCachedProfiles = false, strict = false))
        assertTrue(ShieldRepository.isSubscriptionRefreshFailure(empty, hasCachedProfiles = true, strict = true))
    }
}
