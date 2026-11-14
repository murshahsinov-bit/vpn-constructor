package com.v2ray.ang.shield

import com.v2ray.ang.handler.MmkvManager

/** Small typed wrapper over the shared MMKV settings store. */
object ShieldPrefs {

    fun isBootstrapped(): Boolean =
        MmkvManager.decodeSettingsBool(ShieldConfig.PREF_BOOTSTRAPPED, false)

    fun setBootstrapped(value: Boolean) {
        MmkvManager.encodeSettings(ShieldConfig.PREF_BOOTSTRAPPED, value)
    }

    /** Connect as soon as the app is opened. On by default: the app must work out of the box. */
    fun isAutoConnect(): Boolean =
        MmkvManager.decodeSettingsBool(ShieldConfig.PREF_AUTO_CONNECT, true)

    fun setAutoConnect(value: Boolean) {
        MmkvManager.encodeSettings(ShieldConfig.PREF_AUTO_CONNECT, value)
    }

    /** True once the first-launch latency race has picked a server. */
    fun isServerRanked(): Boolean =
        MmkvManager.decodeSettingsBool(ShieldConfig.PREF_SERVER_RANKED, false)

    fun setServerRanked(value: Boolean) {
        MmkvManager.encodeSettings(ShieldConfig.PREF_SERVER_RANKED, value)
    }
}
