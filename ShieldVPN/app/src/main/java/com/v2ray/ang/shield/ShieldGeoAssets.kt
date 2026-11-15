package com.v2ray.ang.shield

import android.content.Context
import com.v2ray.ang.AppConfig
import com.v2ray.ang.util.LogUtil
import com.v2ray.ang.util.Utils
import java.io.File

/**
 * Unpacks the Xray geo databases into the user asset directory.
 *
 * Every routing profile of the app uses `geosite:`/`geoip:` rules, and Xray
 * rejects the entire config when the databases are missing
 * (`failed to open geosite.dat`). Without them the core exits right after the
 * start command, so the VPN could never come up on a clean install.
 *
 * The databases are shipped inside the APK (`app/src/main/assets`, fetched by
 * `scripts/fetch-libs.sh`) and copied once on first launch: no network round trip
 * and no dependency on GitHub being reachable from Russia.
 */
object ShieldGeoAssets {
    private const val TAG = "ShieldGeoAssets"
    private const val BUFFER_SIZE = 64 * 1024

    private val FILES = listOf(
        AppConfig.GEOSITE_DAT,
        AppConfig.GEOIP_DAT,
        AppConfig.GEOIP_ONLY_CN_PRIVATE_DAT,
    )

    @Volatile
    private var ready = false

    /** Returns true when all databases are in place. Cheap after the first call. */
    @Synchronized
    fun ensure(context: Context): Boolean {
        if (ready) return true

        val dir = Utils.userAssetPath(context)
        if (dir.isNullOrBlank()) return false
        val target = File(dir).apply { mkdirs() }

        var complete = true
        for (name in FILES) {
            val file = File(target, name)
            if (file.length() > 0L) continue
            if (!copyAsset(context, name, file)) complete = false
        }

        if (complete) {
            ready = true
            LogUtil.i(TAG, "geo assets ready: $dir")
        } else {
            LogUtil.e(TAG, "geo assets are incomplete in $dir")
        }
        return complete
    }

    private fun copyAsset(context: Context, name: String, target: File): Boolean {
        val temp = File(target.parentFile, "$name.tmp")
        return try {
            context.assets.open(name).use { input ->
                temp.outputStream().use { output -> input.copyTo(output, BUFFER_SIZE) }
            }
            if (!temp.renameTo(target)) {
                temp.delete()
                LogUtil.e(TAG, "failed to move $name into place")
                return false
            }
            true
        } catch (e: Exception) {
            temp.delete()
            LogUtil.e(TAG, "failed to unpack $name", e)
            false
        }
    }
}
