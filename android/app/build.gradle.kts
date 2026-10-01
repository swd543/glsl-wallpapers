plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.axiom.glswall"
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
