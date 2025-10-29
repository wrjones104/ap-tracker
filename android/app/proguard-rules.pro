# Add project specific ProGuard rules here.
# You can control the set of applied configuration files using the
# proguardFiles setting in build.gradle.
#
# For more details, see
#   http://developer.android.com/guide/developing/tools/proguard.html

# If your project uses WebView with JS, uncomment the following
# and specify the fully qualified class name to the JavaScript interface
# class:
#-keepclassmembers class fqcn.of.javascript.interface.for.webview {
#   public *;
#}

# Uncomment this to preserve the line number information for
# debugging stack traces.
#-keepattributes SourceFile,LineNumberTable

# If you keep the line number information, uncomment this to
# hide the original source file name.
#-renamesourcefileattribute SourceFile

# --- Kotlin Coroutines (THE CRITICAL FIX) ---
# Keep the metadata for all suspend functions and state machines.
# This is what Retrofit needs to read your 'suspend fun' in release mode.
-keepattributes *Annotation*,Signature,Exception,InnerClasses,EnclosingMethod
-keep class kotlin.coroutines.jvm.internal.BaseContinuationImpl { *; }
-keep class * extends kotlin.coroutines.jvm.internal.SuspendLambda { *; }
-keep class * extends kotlin.coroutines.jvm.internal.ContinuationImpl { *; }
-keep class * extends kotlin.jvm.internal.AdaptedFunctionReference { *; }
-keep class kotlin.Metadata { *; }
-keep class kotlinx.coroutines.** { *; }

# --- Keep Generic Type Signatures ---
# This is the rule for your specific error.

# --- Your Code ---
-keep public interface com.jones.aptracker.network.ApiService { *; }
-keep public class com.jones.aptracker.network.** { *; }

# --- Retrofit, OkHttp, Gson ---
-keep class retrofit2.** { *; }
-keep interface retrofit2.** { *; }
-keep class okhttp3.** { *; }
-keep interface okhttp3.** { *; }
-keep class com.google.gson.** { *; }

# --- AppAuth ---
-keep class net.openid.appauth.** { *; }

-keep,allowobfuscation,allowshrinking interface com.jones.aptracker.network.ApiService
-keep,allowobfuscation,allowshrinking class * {
    @retrofit2.http.* <methods>;
}
-keepclassmembers,allowshrinking,allowobfuscation interface * {
    @retrofit2.http.* <methods>;
}