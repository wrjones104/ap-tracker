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

# Crashlytics can only deobfuscate a release stack trace if R8 retains line numbers,
# and the retained source file names are collapsed to a single token so the uploaded
# mapping file stays the only thing that can resolve them. Without these two, every
# release report arrives as method names with no line information.
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile

-keepattributes *Annotation*,Signature,Exception,InnerClasses,EnclosingMethod
-keep class kotlin.coroutines.jvm.internal.BaseContinuationImpl { *; }
-keep class * extends kotlin.coroutines.jvm.internal.SuspendLambda { *; }
-keep class * extends kotlin.coroutines.jvm.internal.ContinuationImpl { *; }
-keep class * extends kotlin.jvm.internal.AdaptedFunctionReference { *; }
-keep class kotlin.Metadata { *; }
-keep class kotlinx.coroutines.** { *; }

-keep public interface com.jones.aptracker.network.ApiService { *; }
-keep public class com.jones.aptracker.network.** { *; }

-keep class retrofit2.** { *; }
-keep interface retrofit2.** { *; }
-keep class okhttp3.** { *; }
-keep interface okhttp3.** { *; }
-keep class com.google.gson.** { *; }

-keep class net.openid.appauth.** { *; }

-keep,allowobfuscation,allowshrinking interface com.jones.aptracker.network.ApiService
-keep,allowobfuscation,allowshrinking class * {
    @retrofit2.http.* <methods>;
}
-keepclassmembers,allowshrinking,allowobfuscation interface * {
    @retrofit2.http.* <methods>;
}

-keep class * extends androidx.room.RoomDatabase
-keep class * implements androidx.room.RoomDatabase
-dontwarn androidx.room.paging.**
-keepclassmembers class * {
    @androidx.room.ColumnInfo <fields>;
    @androidx.room.Embedded <fields>;
    @androidx.room.Relation <fields>;
    @androidx.room.ForeignKey <fields>;
}

# WorkManager reflectively instantiates InputMerger implementations by class name
# (InputMergerFactory.createInputMergerWithDefaultFallback -> getDeclaredConstructor).
# work-runtime ships "-keep class * extends androidx.work.InputMerger", but under R8
# full mode a -keep rule with no member spec does NOT implicitly retain the default
# constructor, so R8 stripped OverwritingInputMerger.<init>() and every one-time
# WorkRequest failed with "Could not create Input Merger" before doWork() ran.
-keep class * extends androidx.work.InputMerger {
    <init>();
}
