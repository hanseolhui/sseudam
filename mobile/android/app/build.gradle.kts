import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

// 업로드 키(저장소에 올리지 않음): ~/.sseudam/keystore.properties
val keyProps = Properties().apply {
    val f = file(System.getProperty("user.home") + "/.sseudam/keystore.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

val sseudamVersion: String = Regex("VERSION = \"([0-9.]+)\"").find(rootProject.file("../../app/version.py").readText())!!.groupValues[1]

android {
    namespace = "kr.sseudam.app"
    compileSdk {
        version = release(36) { minorApiLevel = 1 }
    }

    defaultConfig {
        applicationId = "kr.sseudam.app"
        minSdk = 26
        targetSdk = 36
        // 버전은 컴퓨터 쓰담(app/version.py)과 같게 — GitHub 릴리스 태그와 비교해 자동 업데이트하므로
        versionCode = sseudamVersion.split(".").map { it.toInt() }.let { (a, b, c) -> a * 10000 + b * 100 + c }
        versionName = sseudamVersion
        // 쓰담 플러스 구글 로그인: 구글 클라우드 콘솔의 웹 클라이언트 ID (서버 SSEUDAM_GOOGLE_CLIENT_IDS에도 같은 값)
        // 비어 있으면 '구글로 로그인' 버튼을 숨긴다
        buildConfigField("String", "GOOGLE_WEB_CLIENT_ID", "\"657047512123-bg9e64encuml9hsskioentr0cup4mb0v.apps.googleusercontent.com\"")
    }

    // play: 플레이 스토어용 (자체 업데이트·REQUEST_INSTALL_PACKAGES 없음) → bundlePlayRelease (.aab)
    // github: 직접 설치(APK)용, GitHub 릴리스 자동 업데이트 포함 → assembleGithubRelease (.apk)
    flavorDimensions += "dist"
    productFlavors {
        create("play") {
            dimension = "dist"
            isDefault = true
        }
        create("github") {
            dimension = "dist"
            // 직접 설치 APK는 기기별로 나눠지지 않아서, 글자 인식 네이티브 라이브러리를 휴대폰용(ARM)만 넣어 크기를 줄인다
            // (플레이 .aab 는 스토어가 기기에 맞는 것만 내려보내므로 모두 넣음)
            ndk { abiFilters += listOf("arm64-v8a", "armeabi-v7a") }
        }
    }

    signingConfigs {
        if (keyProps.isNotEmpty()) {
            create("upload") {
                storeFile = file(keyProps.getProperty("storeFile"))
                storePassword = keyProps.getProperty("storePassword")
                keyAlias = keyProps.getProperty("keyAlias")
                keyPassword = keyProps.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            if (keyProps.isNotEmpty()) signingConfig = signingConfigs.getByName("upload")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures { compose = true; buildConfig = true }
    testOptions {
        unitTests {
            isIncludeAndroidResources = true   // Robolectric 스토어 스크린샷용
            all { t ->
                // ./gradlew recordStoreScreenshots 때만 스크린샷을 찍는다 (평소 단위 테스트에서는 건너뜀)
                t.systemProperty("sseudam.screenshots", project.findProperty("sseudam.screenshots") ?: "false")
                t.systemProperty("sseudam.screenshotDir", rootProject.file("store/screenshots").absolutePath)
                t.systemProperty("roborazzi.test.record", "true")
                t.maxHeapSize = "2g"
                if (project.findProperty("sseudam.screenshots") != "true") t.exclude("**/StoreScreenshots*")
            }
        }
    }
}

// 스토어 스크린샷 (JVM에서 Compose 화면 그리기 · 에뮬레이터 필요 없음) → mobile/android/store/screenshots/
tasks.register<Exec>("recordStoreScreenshots") {
    group = "sseudam"
    description = "플레이 스토어 스크린샷을 store/screenshots 에 만든다"
    workingDir = rootProject.projectDir
    commandLine("./gradlew", ":app:testPlayDebugUnitTest", "--tests", "kr.sseudam.app.StoreScreenshots", "-Psseudam.screenshots=true", "--rerun")
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2025.10.01")
    implementation(composeBom)
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.activity:activity-compose:1.11.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.4")
    implementation("androidx.core:core-ktx:1.17.0")
    implementation("androidx.work:work-runtime-ktx:2.10.5")
    implementation("com.journeyapps:zxing-android-embedded:4.3.0")
    // 사진·활동지 글자 읽기: 기기 안 한국어 모델 (앱에 포함, 오프라인)
    implementation("com.google.mlkit:text-recognition-korean:16.0.1")
    // 쓰담 플러스: 구글 로그인 (Credential Manager)
    implementation("androidx.credentials:credentials:1.6.0")
    implementation("androidx.credentials:credentials-play-services-auth:1.6.0")
    implementation("com.google.android.libraries.identity.googleid:googleid:1.2.1")
    // 쓰담 플러스 구독 결제: 플레이판에만 (직접 설치판은 결제 없이 로그인·구독 상태만)
    "playImplementation"("com.android.billingclient:billing-ktx:8.3.0")
    testImplementation("junit:junit:4.13.2")
    // 스토어 스크린샷 (Robolectric + Roborazzi) — 앱에는 들어가지 않음
    testImplementation(composeBom)
    testImplementation("androidx.compose.ui:ui-test-junit4")
    testImplementation("org.robolectric:robolectric:4.16")
    testImplementation("androidx.work:work-testing:2.10.5")
    testImplementation("io.github.takahirom.roborazzi:roborazzi:1.46.1")
    testImplementation("io.github.takahirom.roborazzi:roborazzi-compose:1.46.1")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}
