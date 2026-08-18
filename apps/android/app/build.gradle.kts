import java.util.Properties
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
}

val localProperties = Properties().apply {
    val file = rootProject.file("local.properties")
    if (file.exists()) file.inputStream().use(::load)
}
fun propertyOrEnvironment(name: String, defaultValue: String = ""): String =
    providers.gradleProperty(name).orNull
        ?: System.getenv(name)
        ?: localProperties.getProperty(name)
        ?: defaultValue

val apiBaseUrl = propertyOrEnvironment(
    "FLOODMAN_API_BASE_URL",
    "https://floodman-operations.tail274417.ts.net/mobile-api/"
).let { if (it.endsWith('/')) it else "$it/" }
val squareApplicationId = propertyOrEnvironment("SQUARE_APPLICATION_ID", "REPLACE_WITH_SQUARE_APPLICATION_ID")
val keystorePath = propertyOrEnvironment("FLOODMAN_KEYSTORE_PATH")
val keystorePassword = propertyOrEnvironment("FLOODMAN_KEYSTORE_PASSWORD")
val keyAlias = propertyOrEnvironment("FLOODMAN_KEY_ALIAS")
val keyPassword = propertyOrEnvironment("FLOODMAN_KEY_PASSWORD")
val hasReleaseSigning = listOf(keystorePath, keystorePassword, keyAlias, keyPassword).all { it.isNotBlank() }

android {
    namespace = "com.floodman.operations"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.floodman.operations"
        minSdk = 28
        targetSdk = 36
        versionCode = 13
        versionName = "0.4.0-alpha01"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        vectorDrawables.useSupportLibrary = true
        buildConfigField("String", "FLOODMAN_API_BASE_URL", "\"$apiBaseUrl\"")
        buildConfigField("String", "SQUARE_APPLICATION_ID", "\"$squareApplicationId\"")
        manifestPlaceholders["squareApplicationId"] = squareApplicationId
    }

    signingConfigs {
        if (hasReleaseSigning) {
            create("release") {
                storeFile = file(keystorePath)
                storePassword = keystorePassword
                this.keyAlias = keyAlias
                keyPassword = keyPassword
            }
        }
    }

    buildTypes {
        debug {
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
            isDebuggable = true
        }
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            if (hasReleaseSigning) signingConfig = signingConfigs.getByName("release")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    packaging {
        resources.excludes += setOf(
            "/META-INF/{AL2.0,LGPL2.1}",
            "META-INF/LICENSE*",
            "META-INF/NOTICE*"
        )
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2026.06.00"))
    androidTestImplementation(platform("androidx.compose:compose-bom:2026.06.00"))

    implementation("androidx.core:core-ktx:1.16.0")
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.9.1")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.1")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.9.1")
    implementation("androidx.navigation:navigation-compose:2.9.0")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.biometric:biometric:1.1.0")
    implementation("androidx.fragment:fragment-ktx:1.8.9")
    implementation("androidx.work:work-runtime-ktx:2.10.2")
    implementation("androidx.webkit:webkit:1.14.0")

    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.9.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.squareup.sdk.in-app-payments:card-entry:1.6.8")
    implementation("com.google.ar:core:1.54.0")

    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.10.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.6.1")
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
}
