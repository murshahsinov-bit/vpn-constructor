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

    /** Local ByeDPI bypass. Enabled by default: YouTube is unusable without it in RU. */
    fun isByeDpiEnabled(): Boolean =
        MmkvManager.decodeSettingsBool(ShieldConfig.PREF_BYEDPI_ENABLED, true)

    fun setByeDpiEnabled(value: Boolean) {
        MmkvManager.encodeSettings(ShieldConfig.PREF_BYEDPI_ENABLED, value)
    }

    fun byeDpiArgs(): String =
        MmkvManager.decodeSettingsString(ShieldConfig.PREF_BYEDPI_ARGS)
            ?.takeIf { it.isNotBlank() }
            ?: ShieldConfig.BYEDPI_DEFAULT_ARGS

    fun setByeDpiArgs(value: String) {
        MmkvManager.encodeSettings(ShieldConfig.PREF_BYEDPI_ARGS, value)
    }

    /**
     * PID of the running ciadpi process. The app can be restarted by the system while
     * the child process keeps running, so the pid is persisted to be able to stop the
     * orphan instead of leaking a listener on 127.0.0.1:1080.
     */
    fun byeDpiPid(): Int = MmkvManager.decodeSettingsInt(ShieldConfig.PREF_BYEDPI_PID, 0)

    fun setByeDpiPid(value: Int) {
        MmkvManager.encodeSettings(ShieldConfig.PREF_BYEDPI_PID, value)
    }

    // ------------------------------------------------------------------- auth

    fun authEmail(): String? =
        MmkvManager.decodeSettingsString(ShieldConfig.PREF_AUTH_EMAIL)?.takeIf { it.isNotBlank() }

    fun setAuthEmail(value: String?) {
        MmkvManager.encodeSettings(ShieldConfig.PREF_AUTH_EMAIL, value ?: "")
    }

    fun authName(): String? =
        MmkvManager.decodeSettingsString(ShieldConfig.PREF_AUTH_NAME)?.takeIf { it.isNotBlank() }

    fun setAuthName(value: String?) {
        MmkvManager.encodeSettings(ShieldConfig.PREF_AUTH_NAME, value ?: "")
    }

    /** Firebase UID; absent in local (non-Firebase) mode. */
    fun authUid(): String? =
        MmkvManager.decodeSettingsString(ShieldConfig.PREF_AUTH_UID)?.takeIf { it.isNotBlank() }

    fun setAuthUid(value: String?) {
        MmkvManager.encodeSettings(ShieldConfig.PREF_AUTH_UID, value ?: "")
    }

    /**
     * Account identifier sent to the panel as `?user=`: UID when Firebase is
     * configured, e-mail otherwise. Null while nobody is signed in.
     */
    fun subscriptionUser(): String? = authUid() ?: authEmail()

    /** SHA-256 of the local password. Only used when Firebase is not configured. */
    fun authSecret(): String? =
        MmkvManager.decodeSettingsString(ShieldConfig.PREF_AUTH_SECRET)?.takeIf { it.isNotBlank() }

    fun setAuthSecret(value: String?) {
        MmkvManager.encodeSettings(ShieldConfig.PREF_AUTH_SECRET, value ?: "")
    }

    fun isSignedIn(): Boolean =
        MmkvManager.decodeSettingsBool(ShieldConfig.PREF_AUTH_SIGNED_IN, false)

    fun setSignedIn(value: Boolean) {
        MmkvManager.encodeSettings(ShieldConfig.PREF_AUTH_SIGNED_IN, value)
    }

    // ---------------------------------------------------------------- license

    fun licenseToken(): String? =
        MmkvManager.decodeSettingsString(ShieldConfig.PREF_LICENSE_TOKEN)
            ?.takeIf { it.isNotBlank() }

    fun setLicenseToken(value: String?) {
        MmkvManager.encodeSettings(ShieldConfig.PREF_LICENSE_TOKEN, value ?: "")
    }

    fun licenseExpiresAt(): Long =
        MmkvManager.decodeSettingsLong(ShieldConfig.PREF_LICENSE_EXPIRES_AT, 0L)

    fun setLicenseExpiresAt(value: Long) {
        MmkvManager.encodeSettings(ShieldConfig.PREF_LICENSE_EXPIRES_AT, value)
    }

    fun licensePlan(): String? =
        MmkvManager.decodeSettingsString(ShieldConfig.PREF_LICENSE_PLAN)
            ?.takeIf { it.isNotBlank() }

    fun setLicensePlan(value: String?) {
        MmkvManager.encodeSettings(ShieldConfig.PREF_LICENSE_PLAN, value ?: "")
    }

    fun licenseDevice(): String? =
        MmkvManager.decodeSettingsString(ShieldConfig.PREF_LICENSE_DEVICE)
            ?.takeIf { it.isNotBlank() }

    fun setLicenseDevice(value: String?) {
        MmkvManager.encodeSettings(ShieldConfig.PREF_LICENSE_DEVICE, value ?: "")
    }

    fun licenseTrial(): Boolean =
        MmkvManager.decodeSettingsBool(ShieldConfig.PREF_LICENSE_TRIAL, false)

    fun setLicenseTrial(value: Boolean) {
        MmkvManager.encodeSettings(ShieldConfig.PREF_LICENSE_TRIAL, value)
    }

    fun licenseDeviceId(): String? =
        MmkvManager.decodeSettingsString(ShieldConfig.PREF_LICENSE_DEVICE_ID)
            ?.takeIf { it.isNotBlank() }

    fun setLicenseDeviceId(value: String?) {
        MmkvManager.encodeSettings(ShieldConfig.PREF_LICENSE_DEVICE_ID, value ?: "")
    }
}
