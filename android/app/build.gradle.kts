plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.axiom.glswall"
    // Targeting API 36 (Android 16). The engine uses only long-stable API
    // surface (EGL14/GLES20, DisplayManager, PowerManager,
    // WallpaperService.Engine), verified against the platform-36 stubs.
    // Two API notes that bite if you guess:
    //  * EGL14's public Java API is array+offset style:
    //    eglInitialize(dpy, major, 0, minor, 0) etc. — there is no
    //    three-argument form.
    //  * Surface size is not queryable from Surface/SurfaceHolder in the
    //    public API; it comes from Callback.surfaceChanged.
    compileSdk = 36

    defaultConfig {
        applicationId = "com.axiom.glswall"
        minSdk = 26        // EGL14 + WallpaperService + RECEIVER_NOT_EXPORTED
        targetSdk = 36
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
