import java.io.FileInputStream
import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    id("com.jaredsburrows.license")
}

android {
    namespace = "com.v2ray.ang"
    compileSdk = 37

    // Firebase credentials are optional: without them the app runs the local
    // account mode (see ShieldAuth). CI injects them from repository secrets.
    val localProperties = Properties().apply {
        val file = rootProject.file("local.properties")
        if (file.exists()) file.inputStream().use { load(it) }
    }
    fun secret(name: String): String =
        (findProperty(name) as? String)?.takeIf { it.isNotBlank() }
            ?: localProperties.getProperty(name, "").orEmpty()

    val firebaseApiKey = secret("FIREBASE_API_KEY")
    val firebaseAppId = secret("FIREBASE_APP_ID")
    val firebaseProjectId = secret("FIREBASE_PROJECT_ID")
    val firebaseWebClientId = secret("FIREBASE_WEB_CLIENT_ID")
    val firebaseEnabled = firebaseApiKey.isNotBlank() &&
        firebaseAppId.isNotBlank() &&
        firebaseProjectId.isNotBlank()

    defaultConfig {
        // ShieldVPN branding: separate package so it can live next to the upstream client.
        applicationId = "io.netrun.shieldvpn"
        minSdk = 24
        targetSdk = 37
        versionCode = 1
        versionName = "1.0.0"

        buildConfigField("boolean", "FIREBASE_ENABLED", firebaseEnabled.toString())
        buildConfigField("String", "FIREBASE_API_KEY", "\"$firebaseApiKey\"")
        buildConfigField("String", "FIREBASE_APP_ID", "\"$firebaseAppId\"")
        buildConfigField("String", "FIREBASE_PROJECT_ID", "\"$firebaseProjectId\"")
        buildConfigField("String", "FIREBASE_WEB_CLIENT_ID", "\"$firebaseWebClientId\"")

        // One universal APK for phones (arm64 + armeabi-v7a): the Xray core is ~33 MB per
        // ABI, so bundling every ABI would produce a ~150 MB file.
        // Build a single-ABI APK with e.g. -PABI_FILTERS=arm64-v8a
        // or include emulator ABIs with -PABI_FILTERS=arm64-v8a;x86_64
        val abiFilterList = (properties["ABI_FILTERS"] as? String)?.split(';')
        if (abiFilterList.isNullOrEmpty()) {
            ndk {
                abiFilters += listOf("arm64-v8a", "armeabi-v7a")
            }
        }
        splits {
            abi {
                isEnable = !abiFilterList.isNullOrEmpty()
                reset()
                if (!abiFilterList.isNullOrEmpty()) {
                    include(*abiFilterList.toTypedArray())
                    isUniversalApk = false
                }
            }
        }

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    // Release signing is taken from ShieldVPN/keystore.properties when present.
    // Without it the release build is signed with the debug key, so that
    // `assemblePlaystoreRelease` still produces an installable APK out of the box.
    val keystorePropertiesFile = rootProject.file("keystore.properties")
    val keystoreProperties = Properties().apply {
        if (keystorePropertiesFile.exists()) {
            FileInputStream(keystorePropertiesFile).use { load(it) }
        }
    }

    signingConfigs {
        if (keystorePropertiesFile.exists()) {
            create("shieldRelease") {
                storeFile = file(keystoreProperties.getProperty("storeFile"))
                storePassword = keystoreProperties.getProperty("storePassword")
                keyAlias = keystoreProperties.getProperty("keyAlias")
                keyPassword = keystoreProperties.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            signingConfig = if (keystorePropertiesFile.exists()) {
                signingConfigs.getByName("shieldRelease")
            } else {
                signingConfigs.getByName("debug")
            }
        }
    }

    flavorDimensions.add("distribution")
    productFlavors {
        create("fdroid") {
            dimension = "distribution"
            applicationIdSuffix = ".fdroid"
            buildConfigField("String", "DISTRIBUTION", "\"F-Droid\"")
        }
        create("playstore") {
            dimension = "distribution"
            buildConfigField("String", "DISTRIBUTION", "\"Play Store\"")
        }
    }

    sourceSets {
        getByName("main") {
            jniLibs.srcDirs("libs")
        }
    }

    compileOptions {
        isCoreLibraryDesugaringEnabled = true
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlin {
        compilerOptions {
            jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
        }
    }

    applicationVariants.all {
        val variant = this
        val isFdroid = variant.productFlavors.any { it.name == "fdroid" }
        if (isFdroid) {
            val versionCodes =
                mapOf(
                    "armeabi-v7a" to 2, "arm64-v8a" to 1, "x86" to 4, "x86_64" to 3, "universal" to 0
                )

            variant.outputs
                .map { it as com.android.build.gradle.internal.api.ApkVariantOutputImpl }
                .forEach { output ->
                    val abi = output.getFilter("ABI") ?: "universal"
                    output.outputFileName = "ShieldVPN_${variant.versionName}-fdroid_${abi}.apk"
                    if (versionCodes.containsKey(abi)) {
                        output.versionCodeOverride =
                            (100 * variant.versionCode + versionCodes[abi]!!).plus(5000000)
                    } else {
                        return@forEach
                    }
                }
        } else {
            variant.outputs
                .map { it as com.android.build.gradle.internal.api.ApkVariantOutputImpl }
                .forEach { output ->
                    val abi = if (output.getFilter("ABI") != null)
                        output.getFilter("ABI")
                    else
                        "universal"

                    // Play Store build keeps the plain versionCode from defaultConfig.
                    output.outputFileName = "ShieldVPN_${variant.versionName}_${abi}.apk"
                }
        }
    }

    buildFeatures {
        buildConfig = true
        compose = true
    }

    androidResources {
        generateLocaleConfig = true
        localeFilters += listOf(
            "en",
            "zh-rCN",
            "zh-rTW",
            "vi",
            "ru",
            "fa",
            "ar",
            "az",
            "bn",
            "bqi-rIR"
        )
    }

    packaging {
        jniLibs {
            useLegacyPackaging = true
        }
    }

    testOptions {
        unitTests.all {
            it.useJUnitPlatform()
            // Treat Jupiter discovery warnings as failures: JUnit 4 failed on an invalid @Test
            // method, such as one that returns a value, while Jupiter only warns and skips it.
            // The key is @API(status = EXPERIMENTAL) in JUnit 6; after a JUnit upgrade, check
            // that a temporary `@Test fun probe() = 1` still fails the unit test task.
            it.systemProperty("junit.platform.discovery.issue.severity.critical", "WARNING")
        }
    }

}

dependencies {
    // Core Libraries
    implementation(fileTree(mapOf("dir" to "libs", "include" to listOf("*.aar", "*.jar"))))
    // AndroidX Core Libraries
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)

    // Compose Libraries
    implementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(platform(libs.androidx.compose.bom))

    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.foundation)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.lifecycle.runtime.compose)
    implementation(libs.coil.compose)

    debugImplementation(libs.androidx.compose.ui.tooling)

    // Data and Storage Libraries
    implementation(libs.mmkv.static)
    implementation(libs.gson)
    implementation(libs.okhttp)

    // Accounts: Firebase Auth + Firestore (Spark plan, free tier)
    implementation(platform(libs.firebase.bom))
    implementation(libs.firebase.auth)
    implementation(libs.firebase.firestore)
    implementation(libs.androidx.credentials)
    implementation(libs.androidx.credentials.play.services.auth)
    implementation(libs.googleid)

    // Compile-time only: Firebase puts Guava on the runtime classpath but not on
    // the compile classpath, which is where ListenableFuture has to come from.
    compileOnly("com.google.guava:guava:33.6.0-android")

    // Reactive and Utility Libraries
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.kotlinx.coroutines.core)

    // QR Code: CameraX + ZXing
    implementation(libs.camerax.core)
    implementation(libs.camerax.camera2)
    implementation(libs.camerax.lifecycle)
    implementation(libs.camerax.compose)
    implementation(libs.core) // zxing core

    // AndroidX Lifecycle and Architecture Components
    implementation(libs.lifecycle.viewmodel.ktx)
    implementation(libs.lifecycle.runtime.ktx)

    // Background Task Libraries
    implementation(libs.work.runtime.ktx)
    implementation(libs.work.multiprocess)

    // Reorderable list
    implementation(libs.reorderable)

    // Testing Libraries
    testImplementation(platform(libs.junit.bom))
    testImplementation(libs.junit.jupiter)
    testRuntimeOnly(libs.junit.platform.launcher)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
    testImplementation(libs.mockito.core)
    testImplementation(libs.mockito.kotlin)
    coreLibraryDesugaring(libs.desugar.jdk.libs)
}

// Firebase upgrades com.google.guava:listenablefuture to the intentionally empty
// "9999.0-empty-to-avoid-conflict-with-guava" stub and exposes Guava itself only
// on the runtime classpath. Kotlin then cannot see ListenableFuture, which breaks
// CameraX/WorkManager compilation. Guava ships the interface, so the compile
// classpath gets it explicitly while packaging keeps the empty stub (no duplicate
// classes).
configurations.configureEach {
    resolutionStrategy.eachDependency {
        if (requested.group == "com.google.guava" && requested.name == "listenablefuture") {
            useVersion("9999.0-empty-to-avoid-conflict-with-guava")
            because("Guava provides ListenableFuture; the stub avoids duplicate classes")
        }
    }
}
