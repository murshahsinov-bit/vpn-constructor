package com.v2ray.ang.shield

import android.annotation.SuppressLint
import com.v2ray.ang.handler.MmkvManager
import com.v2ray.ang.util.LogUtil
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID

/**
 * Лицензия ShieldVPN: пробный период или оплаченный тариф.
 *
 * Лицензия — подписанный воркером токен `SVS1.<payload>.<signature>`. Клиент не
 * может её продлить: подпись проверяет панель при выдаче подписки. Локально
 * хранится только сам токен и дата окончания, чтобы приложение работало без
 * сети и показывало остаток дней.
 */
data class ShieldLicenseInfo(
    val token: String,
    val plan: String,
    val device: String,
    /** Unix-время окончания, секунды. */
    val expiresAt: Long,
    val trial: Boolean,
) {
    val daysLeft: Int
        get() {
            val seconds = expiresAt - System.currentTimeMillis() / 1000L
            if (seconds <= 0) return 0
            return ((seconds + 86_399) / 86_400).toInt()
        }

    val isActive: Boolean get() = daysLeft > 0

    fun planTitle(): String = when (plan) {
        ShieldLicense.PLAN_TRIAL -> "Пробный период"
        "m1" -> "1 месяц"
        "m3" -> "3 месяца"
        "m12" -> "12 месяцев"
        else -> "Подписка"
    }
}

object ShieldLicense {

    const val PLAN_TRIAL = "trial"

    private const val TAG = "ShieldVPN"
    private const val CONNECT_TIMEOUT_MS = 12_000
    private const val READ_TIMEOUT_MS = 15_000

    /** Лицензия из хранилища, даже если уже истекла: UI должен показать 0 дней. */
    fun cached(): ShieldLicenseInfo? {
        val token = ShieldPrefs.licenseToken() ?: return null
        val expiresAt = ShieldPrefs.licenseExpiresAt()
        if (expiresAt <= 0L) return null
        return ShieldLicenseInfo(
            token = token,
            plan = ShieldPrefs.licensePlan() ?: "",
            device = ShieldPrefs.licenseDevice() ?: "android",
            expiresAt = expiresAt,
            trial = ShieldPrefs.licenseTrial(),
        )
    }

    fun active(): ShieldLicenseInfo? = cached()?.takeIf { it.isActive }

    /** Стабильный идентификатор установки — только для лимита триала. */
    fun deviceId(): String {
        ShieldPrefs.licenseDeviceId()?.let { return it }
        val generated = "android-" + UUID.randomUUID().toString().replace("-", "")
        ShieldPrefs.setLicenseDeviceId(generated)
        return generated
    }

    /**
     * Активирует лицензию по ссылке из бота (`https://…/activate/SVS1…`),
     * deep link (`shieldvpn://activate?token=…`) или просто по коду.
     */
    fun activate(raw: String): ShieldLicenseInfo {
        val token = extractToken(raw)
        require(token.isNotEmpty()) { "Ссылка не распознана. Скопируйте её целиком." }
        val body = post("/api/activate", JSONObject().put("link", raw))
        return persist(body)
    }

    /** Пробный период на это устройство. */
    fun requestTrial(): ShieldLicenseInfo {
        val body = post(
            "/api/trial",
            JSONObject()
                .put("device", "android")
                .put("device_id", deviceId()),
        )
        return persist(body)
    }

    /**
     * Перепроверяет лицензию на панели. Null — сеть недоступна или лицензия
     * больше не действует; вызывающий решает, показывать кэш или ошибку.
     */
    fun refresh(): ShieldLicenseInfo? {
        val token = ShieldPrefs.licenseToken() ?: return null
        val body = runCatching { get("/api/license?token=${encode(token)}") }.getOrElse {
            LogUtil.d(TAG, "license refresh failed: ${it.message}")
            return null
        }
        return persist(body)
    }

    fun clear() {
        ShieldPrefs.setLicenseToken(null)
        ShieldPrefs.setLicenseExpiresAt(0L)
        ShieldPrefs.setLicensePlan(null)
        ShieldPrefs.setLicenseDevice(null)
        ShieldPrefs.setLicenseTrial(false)
    }

    // ------------------------------------------------------------------ storage

    private fun persist(body: JSONObject): ShieldLicenseInfo {
        val token = body.optString("token")
            .ifBlank { extractToken(body.optString("subscription_url")) }
            .ifBlank { extractToken(body.optString("ios_url")) }
            .ifBlank { ShieldPrefs.licenseToken().orEmpty() }
        require(token.isNotEmpty()) { "Сервис не вернул лицензию" }

        val expiresAt = body.optLong("expires_at", 0L).takeIf { it > 0L }
            ?: parseDate(body.optString("expires_on"))
            ?: error("Сервис не вернул срок действия")

        val info = ShieldLicenseInfo(
            token = token,
            plan = body.optString("plan"),
            device = body.optString("device").ifBlank { "android" },
            expiresAt = expiresAt,
            trial = body.optBoolean("trial") || body.optString("plan") == PLAN_TRIAL,
        )
        ShieldPrefs.setLicenseToken(info.token)
        ShieldPrefs.setLicenseExpiresAt(info.expiresAt)
        ShieldPrefs.setLicensePlan(info.plan)
        ShieldPrefs.setLicenseDevice(info.device)
        ShieldPrefs.setLicenseTrial(info.trial)
        return info
    }

    /** `2026-12-19` → конец этого дня по UTC, в секундах. */
    @SuppressLint("SimpleDateFormat")
    private fun parseDate(value: String): Long? {
        val clean = value.trim()
        if (clean.length != 10) return null
        return runCatching {
            val date = java.time.LocalDate.parse(clean)
            date.plusDays(1).atStartOfDay(java.time.ZoneOffset.UTC).toEpochSecond() - 1
        }.getOrNull()
    }

    private fun encode(value: String): String =
        java.net.URLEncoder.encode(value, "UTF-8")

    internal fun extractToken(raw: String): String {
        val match = TOKEN_RE.find(raw.trim()) ?: return ""
        return match.value
    }

    private val TOKEN_RE = Regex("SVS1\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+")

    // ------------------------------------------------------------------ network

    private fun post(path: String, payload: JSONObject): JSONObject =
        request("POST", path, payload.toString())

    private fun get(path: String): JSONObject = request("GET", path, null)

    private fun request(method: String, path: String, body: String?): JSONObject {
        val url = URL(ShieldConfig.PANEL_API_BASE_URL + path)
        var current = url
        var redirects = 0
        while (true) {
            val connection = (current.openConnection() as HttpURLConnection).apply {
                requestMethod = method
                connectTimeout = CONNECT_TIMEOUT_MS
                readTimeout = READ_TIMEOUT_MS
                instanceFollowRedirects = true
                setRequestProperty("Accept", "application/json")
                setRequestProperty("User-Agent", "ShieldVPN-Android")
                if (body != null) {
                    doOutput = true
                    setRequestProperty("Content-Type", "application/json")
                }
            }
            try {
                if (body != null) {
                    connection.outputStream.use { it.write(body.toByteArray()) }
                }
                val code = connection.responseCode
                if (code in 300..399 && redirects < 3) {
                    val location = connection.getHeaderField("Location")
                    if (!location.isNullOrBlank()) {
                        current = URL(current, location)
                        redirects++
                        continue
                    }
                }
                val stream = if (code in 200..299) connection.inputStream else connection.errorStream
                val text = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
                val json = runCatching { JSONObject(text) }.getOrDefault(JSONObject())
                if (code !in 200..299) {
                    throw LicenseServerException(code, messageFor(code, json))
                }
                return json
            } finally {
                connection.disconnect()
            }
        }
    }

    private fun messageFor(code: Int, json: JSONObject): String = when {
        json.optString("error") == "trial_already_used" -> TRIAL_USED
        code == 409 -> TRIAL_USED
        code == 403 -> "Лицензия недействительна или истекла"
        code == 503 -> "Сервис активации недоступен, попробуйте позже"
        else -> json.optString("message").ifBlank {
            json.optString("error").ifBlank { "Сервис ответил ошибкой $code" }
        }
    }

    const val TRIAL_USED = "Пробный период уже использован на этом устройстве"

    class LicenseServerException(val code: Int, override val message: String) : IOException(message)
}
