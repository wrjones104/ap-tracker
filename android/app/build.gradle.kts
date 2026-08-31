import java.util.Properties
import java.io.FileInputStream

val localProperties = Properties()
val localPropertiesFile = project.file("local.properties")
if (localPropertiesFile.exists()) {
    localProperties.load(FileInputStream(localPropertiesFile))
}

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    id("com.google.gms.google-services")
    alias(libs.plugins.kotlin.ksp)
}

android {
    flavorDimensions += listOf("environment")
    namespace = "com.jones.aptracker"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.jones.aptracker"
        minSdk = 26
        targetSdk = 36
        versionCode = 73
        versionName = "1.9.1"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        manifestPlaceholders["appAuthRedirectScheme"] = "com.jones.aptracker"
        buildConfigField(
            "String",
            "DISCORD_CLIENT_ID",
            "\"${localProperties.getProperty("DISCORD_CLIENT_ID", "ABCXYZ")}\""
        )
    }

    productFlavors {

        create("dev") {
            dimension = "environment"
            applicationIdSuffix = ".dev"
            val devUrl = localProperties.getProperty("DEV_API_BASE_URL") ?: "http://10.0.2.2:5000/"
            buildConfigField("String", "API_BASE_URL", "\"$devUrl\"")
        }

        create("uat") {
            dimension = "environment"
            applicationIdSuffix = ".uat"
            val uatUrl = localProperties.getProperty("UAT_API_BASE_URL") ?: throw org.gradle.api.GradleException("UAT_API_BASE_URL not found in local.properties")
            buildConfigField("String", "API_BASE_URL", "\"$uatUrl\"")
        }

        create("prod") {
            dimension = "environment"
            val prodUrl = localProperties.getProperty("PROD_API_BASE_URL") ?: throw org.gradle.api.GradleException("PROD_API_BASE_URL not found in local.properties")
            buildConfigField("String", "API_BASE_URL", "\"$prodUrl\"")
        }
    }

    buildTypes {

        getByName("debug") {
            applicationIdSuffix = ".debug"
            isDebuggable = true
        }

        getByName("release") {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            ndk {
                debugSymbolLevel = "FULL"
            }
        }

        // Runs the exact R8 pipeline as release, but debuggable and debug-signed.
        // Exists so minification faults -- stripped reflective constructors, missing
        // keep rules, obfuscated Gson models -- surface during testing rather than in
        // the Play Store build, where they are only visible as runtime failures.
        create("minified") {
            initWith(getByName("release"))
            isDebuggable = true
            signingConfig = signingConfigs.getByName("debug")
            // google-services.json only declares clients for com.jones.aptracker and
            // com.jones.aptracker.debug, so this reuses the debug application id
            // instead of taking a suffix of its own. It installs over prodDebug.
            applicationIdSuffix = ".debug"
        }
    }

    sourceSets {
        // The minified build type ships no sources of its own, so it reuses the debug
        // manifest for its network security config -- devMinified talks to 10.0.2.2
        // over cleartext and would otherwise be blocked. Launcher icons deliberately
        // come from the flavor, so a minified build looks exactly like the real one.
        getByName("minified").manifest.srcFile("src/debug/AndroidManifest.xml")
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_11)
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.activity)
    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)
    debugImplementation(libs.androidx.compose.ui.tooling)
    debugImplementation(libs.androidx.compose.ui.test.manifest)
    implementation(platform("com.google.firebase:firebase-bom:33.9.0"))
    implementation("com.google.firebase:firebase-messaging-ktx")
    implementation("com.squareup.retrofit2:retrofit:2.9.0")
    implementation("com.squareup.retrofit2:converter-gson:2.9.0")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.8.7")
    implementation("androidx.lifecycle:lifecycle-process:2.8.7")
    // Home of LocalLifecycleOwner since 2.8. The compose-ui copy is deprecated.
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.navigation:navigation-compose:2.8.5")
    implementation("androidx.fragment:fragment-ktx:1.7.1")
    implementation("androidx.compose.material:material-icons-extended-android:1.6.6")
    implementation("com.squareup.okhttp3:logging-interceptor:4.12.0")
    implementation("com.google.accompanist:accompanist-swiperefresh:0.28.0")
    val room_version = "2.8.4"
    implementation("androidx.room:room-runtime:$room_version")
    ksp("androidx.room:room-compiler:$room_version")
    implementation("androidx.room:room-ktx:$room_version")
    implementation("net.openid:appauth:0.11.1")
    implementation("androidx.security:security-crypto:1.1.0-alpha06")
    implementation("io.coil-kt:coil-compose:2.6.0")
    implementation(libs.androidx.compose.foundation)
    implementation("androidx.datastore:datastore-preferences:1.1.1")
    implementation("androidx.work:work-runtime-ktx:2.9.1")
    implementation(libs.androidx.glance.appwidget)
    implementation(libs.androidx.glance.material3)
}