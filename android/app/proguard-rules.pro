# --- General Settings ---
# preserve line numbers for debugging stack traces.
-keepattributes SourceFile,LineNumberTable

# --- Kotlin Coroutines ---
# Essential for Retrofit and stability
-keepattributes *Annotation*,Signature,Exception,InnerClasses,EnclosingMethod
-keep class kotlin.coroutines.jvm.internal.BaseContinuationImpl { *; }
-keep class * extends kotlin.coroutines.jvm.internal.SuspendLambda { *; }
-keep class * extends kotlin.coroutines.jvm.internal.ContinuationImpl { *; }
-keep class * extends kotlin.jvm.internal.AdaptedFunctionReference { *; }
-keep class kotlin.Metadata { *; }
-keep class kotlinx.coroutines.** { *; }

# --- Android Room (SQLite) ---
# Required even if you only use DB heavily in Dev, as the library is present in Prod
-keep class * extends androidx.room.RoomDatabase
-keep class * implements androidx.room.RoomDatabase
-dontwarn androidx.room.paging.**
-keepclassmembers class * {
    @androidx.room.ColumnInfo <fields>;
    @androidx.room.Embedded <fields>;
    @androidx.room.Relation <fields>;
    @androidx.room.ForeignKey <fields>;
}

# --- Network & JSON Models ---
# Keep Retrofit interfaces
-keep public interface com.jones.aptracker.network.ApiService { *; }

# IMPORTANT: This protects your Data Classes used by Gson
# It keeps any field explicitly marked with @SerializedName
-keepclassmembers,allowobfuscation class * {
    @com.google.gson.annotations.SerializedName <fields>;
}

# --- Third Party Libraries ---
# Retrofit, OkHttp, Gson
-keep class retrofit2.** { *; }
-keep interface retrofit2.** { *; }
-keep class okhttp3.** { *; }
-keep interface okhttp3.** { *; }
-keep class com.google.gson.** { *; }

# AppAuth
-keep class net.openid.appauth.** { *; }