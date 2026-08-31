// Top-level build file where you can add configuration options common to all sub-projects/modules.
plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.android) apply false
    alias(libs.plugins.kotlin.compose) apply false
    // 4.4.2 moved gmpAppId.txt to a per-variant path. On 4.4.1 every variant wrote the same
    // file, which the Crashlytics mapping upload task reads -- so building two variants in one
    // invocation failed Gradle's implicit-dependency check.
    id("com.google.gms.google-services") version "4.4.4" apply false
    id("com.google.firebase.crashlytics") version "3.0.8" apply false
}
