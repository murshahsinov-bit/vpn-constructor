package io.github.saeeddev94.xray

import android.app.Application
import io.github.saeeddev94.xray.database.XrayDatabase
import io.github.saeeddev94.xray.repository.ConfigRepository
import io.github.saeeddev94.xray.repository.LinkRepository
import io.github.saeeddev94.xray.repository.ProfileRepository
import kotlinx.serialization.json.Json

class Xray : Application() {

    private val xrayDatabase by lazy { XrayDatabase.ref(this) }
    val configRepository by lazy { ConfigRepository(xrayDatabase.configDao()) }
    val linkRepository by lazy { LinkRepository(xrayDatabase.linkDao()) }
    val profileRepository by lazy { ProfileRepository(xrayDatabase.profileDao()) }

    companion object {
        fun Json() = Json {
            ignoreUnknownKeys = true
            encodeDefaults = true
            prettyPrint = true
            prettyPrintIndent = "  "
        }
    }
}
