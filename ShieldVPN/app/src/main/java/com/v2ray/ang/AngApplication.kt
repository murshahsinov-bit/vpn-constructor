package com.v2ray.ang

import android.app.Application
import android.content.Context
import androidx.core.content.ContextCompat
import androidx.work.Configuration
import androidx.work.WorkManager
import com.google.firebase.FirebaseApp
import com.google.firebase.FirebaseOptions
import com.v2ray.ang.AppConfig.ANG_PACKAGE
import com.v2ray.ang.handler.AppLocaleManager
import com.v2ray.ang.handler.MmkvManager
import com.v2ray.ang.handler.SettingsManager
import com.v2ray.ang.shield.ShieldAuth
import com.v2ray.ang.shield.ShieldGeoAssets
import com.v2ray.ang.ui.compose.ThemeManager

class AngApplication : Application() {
    companion object {
        lateinit var application: AngApplication
    }

    /**
     * Attaches the base context to the application.
     * @param base The base context.
     */
    override fun attachBaseContext(base: Context?) {
        super.attachBaseContext(base?.let(ContextCompat::getContextForLanguage))
        application = this
    }

    private val workManagerConfiguration: Configuration = Configuration.Builder()
        .setDefaultProcessName("${ANG_PACKAGE}:bg")
        .build()

    /**
     * Initializes the application.
     */
    override fun onCreate() {
        super.onCreate()

        MmkvManager.initialize(this)

        AppLocaleManager.initialize(this)

        // Initialize WorkManager with the custom configuration
        WorkManager.initialize(this, workManagerConfiguration)

        // Ensure critical preference defaults are present in MMKV early
        SettingsManager.initApp(this)

        // Firebase is optional: only builds with injected credentials initialize it.
        if (BuildConfig.FIREBASE_ENABLED) {
            runCatching {
                if (FirebaseApp.getApps(this).isEmpty()) {
                    FirebaseApp.initializeApp(
                        this,
                        FirebaseOptions.Builder()
                            .setApiKey(BuildConfig.FIREBASE_API_KEY)
                            .setApplicationId(BuildConfig.FIREBASE_APP_ID)
                            .setProjectId(BuildConfig.FIREBASE_PROJECT_ID)
                            .build(),
                    )
                }
            }
        }
        ShieldAuth.initialize(this)

        // Unpack the Xray geo databases in the background: the core cannot start
        // without them, and the connect flow waits for this copy anyway.
        Thread {
            runCatching { ShieldGeoAssets.ensure(this) }
        }.apply { isDaemon = true }.start()

        // Initialize theme state from MMKV
        ThemeManager.refresh()
    }
}
