# 쓰담 R8 규칙 (release 빌드는 minify + shrinkResources)

# QR 읽기 (zxing-android-embedded) — 리플렉션으로 카메라 설정을 읽음
-keep class com.journeyapps.** { *; }
-keep class com.google.zxing.** { *; }

# WorkManager: 일꾼 클래스는 이름으로 만들어지므로 생성자 (Context, WorkerParameters) 유지
# (work-runtime 의 consumer 규칙에도 있지만 앱 쪽에서도 확실히)
-keep class * extends androidx.work.ListenableWorker {
    public <init>(android.content.Context, androidx.work.WorkerParameters);
}

# WorkManager 내부 Room DB: 생성자를 리플렉션으로 부른다. 없으면 앱 시작 때
# 'NoSuchMethodException: WorkDatabase_Impl.<init>' 으로 죽는다 (에뮬레이터에서 확인)
-keep class * extends androidx.room.RoomDatabase { <init>(...); }
-keep class androidx.work.impl.** { *; }

# ML Kit 글자 인식(한국어, 앱 포함 모델)
# 일부만 남기면 시작할 때 MlKitInitProvider 가 'Unsatisfied dependency' 로 죽는다 (에뮬레이터에서 확인).
# ML Kit 구성요소 등록·네이티브(JNI) 연결이 클래스 이름에 기대므로 ML Kit 쪽은 통째로 유지.
-keep class com.google.mlkit.** { *; }
-keep class com.google.android.gms.internal.mlkit_vision_text_bundled_common.** { *; }
-keep class com.google.android.gms.internal.mlkit_vision_common.** { *; }
-keep class com.google.android.gms.internal.mlkit_common.** { *; }
-keep class com.google.firebase.components.** { *; }
-dontwarn com.google.mlkit.**

# JSON 은 안드로이드 기본 org.json 을 손으로 읽고 써서(리플렉션 없음) 따로 규칙이 필요 없다.

# 크래시 보고에 줄 번호가 남게 (플레이 콘솔에 mapping.txt 가 자동으로 함께 올라감)
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile
