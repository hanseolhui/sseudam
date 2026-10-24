package kr.sseudam.app

import android.Manifest
import android.content.Context
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.FileProvider
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.korean.KoreanTextRecognizerOptions
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import java.io.File
import kotlin.coroutines.resume

/**
 * 사진 속 글자 읽기 (아이폰 PhotoText 와 같은 역할).
 * ML Kit 한국어 글자 인식 — 모델이 앱에 들어 있어 기기 안에서만 처리 (사진·글자를 밖으로 보내지 않음).
 */
object PhotoText {
    suspend fun read(ctx: Context, uri: Uri): String {
        val image = runCatching { InputImage.fromFilePath(ctx, uri) }.getOrNull() ?: return ""
        val rec = TextRecognition.getClient(KoreanTextRecognizerOptions.Builder().build())
        return try {
            suspendCancellableCoroutine { c ->
                rec.process(image)
                    .addOnSuccessListener { r -> if (c.isActive) c.resume(r.textBlocks.joinToString("\n") { it.text }.trim()) }
                    .addOnFailureListener { if (c.isActive) c.resume("") }
            }
        } finally { rec.close() }
    }

    /** 카메라 사진을 잠깐 둘 곳 (FileProvider 'photos' 경로) */
    fun newCameraUri(ctx: Context): Uri {
        val dir = File(ctx.cacheDir, "photos").apply { mkdirs() }
        dir.listFiles()?.forEach { it.delete() }
        val f = File(dir, "scan-${System.currentTimeMillis()}.jpg")
        return FileProvider.getUriForFile(ctx, ctx.packageName + ".files", f)
    }

    fun clearCamera(ctx: Context) { File(ctx.cacheDir, "photos").listFiles()?.forEach { it.delete() } }
}

/**
 * "활동지 찍기 · 사진에서" 버튼 묶음 → 글자 읽기 → onText (선생님이 고쳐서 담기).
 * 사진 고르기는 시스템 사진 선택기(저장소 권한 없음). 카메라는 앱 매니페스트에 CAMERA(QR 읽기용)가 있어서
 * 안드로이드 규칙상 찍기 전에 카메라 권한을 받아야 한다.
 */
@Composable
fun PhotoTextButtons(onText: (String) -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var reading by remember { mutableStateOf(false) }
    var msg by remember { mutableStateOf("") }
    var cameraUri by rememberSaveable { mutableStateOf<Uri?>(null) }  // 카메라 앱 다녀오는 사이 화면이 다시 만들어져도 유지

    fun handle(uri: Uri, fromCamera: Boolean) {
        reading = true; msg = ""
        scope.launch {
            val t = PhotoText.read(ctx, uri)
            if (fromCamera) PhotoText.clearCamera(ctx)
            reading = false
            if (t.isBlank()) msg = "글자를 찾지 못했어요. 밝은 곳에서 글자가 크게 나오게 다시 찍어 주세요."
            else { msg = "✓ 읽은 글을 기록 칸에 넣었어요 · 고친 뒤 ‘담기’를 눌러 주세요"; onText(t) }
        }
    }

    val pick = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri -> if (uri != null) handle(uri, false) }
    val take = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { ok ->
        val u = cameraUri
        if (ok && u != null) handle(u, true) else PhotoText.clearCamera(ctx)
    }
    fun launchCamera() { PhotoText.newCameraUri(ctx).also { cameraUri = it; take.launch(it) } }
    val camPerm = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        if (ok) launchCamera() else msg = "카메라를 허용하면 활동지를 바로 찍을 수 있어요. ‘사진에서’로 골라도 돼요."
    }

    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ChipButton("📷 활동지 찍기") {
                if (reading) return@ChipButton
                if (granted(ctx, Manifest.permission.CAMERA)) launchCamera() else camPerm.launch(Manifest.permission.CAMERA)
            }
            ChipButton("🖼️ 사진에서") {
                if (!reading) pick.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
            }
            if (reading) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
        }
        if (msg.isNotEmpty()) Text(msg, fontSize = 12.sp, color = if (msg.startsWith("✓")) T.mint else T.coral)
    }
}
