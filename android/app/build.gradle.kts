plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.axiom.glswall"
    // API 35 on purpose. The API-36 (Android 16) platform jar breaks the
    // classic EGL14 API: eglInitialize/eglChooseConfig/... now take
    // array+offset pairs and eglCreateWindowSurface takes java.lang.Object,
    // SurfaceHolder lost getSurfaceWidth/getSurfaceHeight, and
    // WallpaperManager.sendWallpaperCommand lost its ComponentName-targeted
    // overload (verified against platform-36_r02.zip stubs + AOSP main).
    // Code compiled against those signatures would NoSuchMethodError on
    // every sub-16 device, so the MVP targets 35 and stays classic-API
    // everywhere; the power model below makes the 16+ AOD wake-lock change
    // (DISABLE_DRAW_WAKE_LOCK_WALLPAPER) moot either way.
    compileSdk = 35

    defaultConfig {
        applicationId = "com.axiom.glswall"
        minSdk = 26        // EGL14 + WallpaperService + RECEIVER_NOT_EXPORTED
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

// Zero runtime dependencies: the wallpaper is pure android.* + android.opengl.
dependencies {
}
