package kr.sseudam.app

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.widget.Toast
import android.os.Build
import android.provider.Settings
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.credentials.CredentialManager
import androidx.credentials.CustomCredential
import androidx.credentials.GetCredentialRequest
import androidx.credentials.exceptions.GetCredentialCancellationException
import androidx.credentials.exceptions.GetCredentialException
import androidx.credentials.exceptions.NoCredentialException
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.google.android.libraries.identity.googleid.GetGoogleIdOption
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID

/** 구독 상품 하나 (플레이 기본 요금제: month · half · year) */
data class PlusOffer(val basePlanId: String, val title: String, val price: String,
                     val periodMonths: Int? = null, val monthlyEquivalent: String? = null,
                     val includedAiCount: Int? = null)

internal data class PlanBenefit(val cap: Int, val months: Int)

/**
 * 쓰담 플러스 계정 (구글 · 이메일 로그인) 과 구독 상태.
 * 같은 계정으로 컴퓨터 쓰담에 로그인하면 AI 정리 · 초안을 쓴다. 결제 확인은 서리아트 서버가 구글 플레이 API로 한다.
 * 결제(플레이 결제 라이브러리)는 배포판별 PlusBilling (src/play · src/github).
 */
object Plus {
    // New purchases also require a fresh server iap-config response. Restore is independent.
    const val SALES_ENABLED = true
    const val SALES_NOTICE = "유료 상품 곧 오픈"
    const val STORE_PURCHASE_NOTICE = "구독은 Google Play 또는 App Store에서 받은 쓰담 앱에서 할 수 있어요."
    const val API = "https://apps.seoriarts.com/api/sseudam-plus"
    const val MANAGE_URL = "https://play.google.com/store/account/subscriptions?sku=plus&package=kr.sseudam.app"
    const val TERMS_URL = "https://apps.seoriarts.com/sseudam-plus-terms"
    const val PRIVACY_URL = "https://apps.seoriarts.com/sseudam-privacy"

    data class Status(val active: Boolean = false, val planName: String = "", val endsAt: String = "",
                      val daysToEnd: Int = 0, val autoRenew: Boolean = false)

    private val _email = MutableStateFlow<String?>(null)
    val email: StateFlow<String?> = _email
    private val _loggedIn = MutableStateFlow(false)
    val loggedIn: StateFlow<Boolean> = _loggedIn
    private val _status = MutableStateFlow(Status())
    val status: StateFlow<Status> = _status
    val busy = MutableStateFlow(false)
    val message = MutableStateFlow("")
    private val _salesReady = MutableStateFlow(false)
    val salesReady: StateFlow<Boolean> = _salesReady
    private val _purchaseNotice = MutableStateFlow("로그인하면 구독 상품을 확인할 수 있어요.")
    val purchaseNotice: StateFlow<String> = _purchaseNotice
    /** 플레이 결제에 붙이는 계정 표시 (서버가 이 결제를 이 계정에 잇는다) */
    @Volatile var accountToken: String? = null; private set
    /** 서버 iap-config 의 기본 요금제 순서 */
    @Volatile var basePlans: List<String> = listOf("month", "half", "year"); private set
    @Volatile internal var planBenefits: Map<String, PlanBenefit> = emptyMap(); private set

    private lateinit var ctx: Context

    fun init(c: Context) {
        if (::ctx.isInitialized) return
        ctx = c.applicationContext
        _email.value = prefs.getString("plusEmail", null)
        _loggedIn.value = token != null
        PlusBilling.init(ctx)
    }

    // 로그인 토큰은 앱 전용 저장소에 (백업 꺼짐 · 다른 앱은 못 읽음)
    private val prefs get() = ctx.getSharedPreferences("sseudam_plus", Context.MODE_PRIVATE)
    private var token: String?
        get() = prefs.getString("token", null)
        set(v) { prefs.edit().apply { if (v == null) remove("token") else putString("token", v) }.apply(); _loggedIn.value = v != null }

    private val installId: String get() = prefs.getString("install", null)
        ?: UUID.randomUUID().toString().also { prefs.edit().putString("install", it).apply() }

    private val device: String get() =
        (runCatching { Settings.Global.getString(ctx.contentResolver, Settings.Global.DEVICE_NAME) }.getOrNull() ?: Build.MODEL).take(40)

    /** 서버에 JSON 보내기 (IO 스레드). 200이 아니면 서버가 준 한국어 오류로 예외 */
    private suspend fun post(body: JSONObject): JSONObject = withContext(Dispatchers.IO) {
        val conn = URL(API).openConnection() as HttpURLConnection
        try {
            conn.requestMethod = "POST"; conn.doOutput = true
            conn.connectTimeout = 30000; conn.readTimeout = 30000
            conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
            conn.outputStream.use { it.write(body.toString().toByteArray()) }
            val code = conn.responseCode
            val text = runCatching { (if (code in 200..299) conn.inputStream else conn.errorStream)?.bufferedReader()?.readText() }.getOrNull() ?: ""
            val j = runCatching { JSONObject(text) }.getOrElse { JSONObject() }
            if (code != 200) {
                if (j.optBoolean("loggedOut")) withContext(Dispatchers.Main) {
                    if (body.opt("token") == token) clear()
                }
                throw Exception(j.optString("error").ifEmpty { "서버에 연결하지 못했어요." })
            }
            j
        } catch (e: java.io.IOException) {
            throw Exception("서버에 연결하지 못했어요.")
        } finally { conn.disconnect() }
    }

    private fun apply(j: JSONObject) {
        j.optString("email").ifEmpty { null }?.let { if (_email.value != it) { accountToken = null; _salesReady.value = false }; _email.value = it; prefs.edit().putString("plusEmail", it).apply() }
        j.optString("token").ifEmpty { null }?.let { token = it }
        j.optJSONObject("sub")?.let { s ->
            _status.value = Status(s.optBoolean("active"), s.optString("planName"), s.optString("endsAt"),
                s.optInt("daysToEnd"), s.optBoolean("autoRenew"))
        }
    }

    private fun clear() {
        token = null; _email.value = null; _status.value = Status(); accountToken = null
        _salesReady.value = false
        _purchaseNotice.value = "로그인하면 구독 상품을 확인할 수 있어요."
        prefs.edit().remove("plusEmail").apply()
    }

    private suspend fun call(f: suspend () -> JSONObject) {
        busy.value = true
        try { apply(f()); message.value = ""; loadProducts() }
        catch (e: kotlinx.coroutines.CancellationException) { throw e }
        catch (e: Exception) { message.value = e.message ?: "서버에 연결하지 못했어요." }
        finally { busy.value = false }
    }

    // 로그인
    val googleEnabled: Boolean get() = BuildConfig.GOOGLE_WEB_CLIENT_ID.isNotEmpty()

    /** 구글 계정 고르기 (Credential Manager) → ID 토큰을 서버가 확인 */
    suspend fun signInGoogle(activity: Activity) {
        val option = GetGoogleIdOption.Builder()
            .setServerClientId(BuildConfig.GOOGLE_WEB_CLIENT_ID)
            .setFilterByAuthorizedAccounts(false)
            .setAutoSelectEnabled(false)
            .build()
        val idToken = try {
            val r = CredentialManager.create(activity).getCredential(activity, GetCredentialRequest.Builder().addCredentialOption(option).build())
            val c = r.credential
            if (c is CustomCredential && c.type == GoogleIdTokenCredential.TYPE_GOOGLE_ID_TOKEN_CREDENTIAL)
                GoogleIdTokenCredential.createFrom(c.data).idToken
            else { message.value = "구글 로그인을 하지 못했어요."; return }
        } catch (e: GetCredentialCancellationException) { return }
        catch (e: NoCredentialException) { message.value = "이 폰에 구글 계정이 없어요. 설정에서 계정을 추가하거나 이메일로 로그인해 주세요."; return }
        catch (e: GetCredentialException) { message.value = "구글 로그인을 하지 못했어요."; return }
        catch (e: Exception) { message.value = "구글 로그인을 하지 못했어요."; return }
        call { post(JSONObject().put("action", "social").put("provider", "google").put("idToken", idToken)
            .put("installId", installId).put("phone", true).put("deviceName", device)) }
    }

    suspend fun sendCode(mail: String): Boolean {
        busy.value = true
        return try {
            post(JSONObject().put("action", "start").put("email", mail.trim().lowercase()).put("installId", installId))
            message.value = "✓ 메일로 온 인증번호를 넣어 주세요."; true
        } catch (e: Exception) { message.value = e.message ?: ""; false }
        finally { busy.value = false }
    }

    suspend fun verify(mail: String, code: String) = call {
        post(JSONObject().put("action", "verify").put("email", mail.trim().lowercase()).put("code", code.trim())
            .put("installId", installId).put("phone", true).put("deviceName", device))
    }

    suspend fun refresh() {
        val t = token ?: return
        runCatching { post(JSONObject().put("action", "status").put("token", t)) }
            .onSuccess { if (token == t) apply(it) }
    }

    suspend fun logout() {
        if (busy.value) return
        val t = token
        clear()
        t?.let { runCatching { post(JSONObject().put("action", "logout").put("token", it)) } }
    }

    /** 계정 삭제 — 로그인 · 기기 · 선생님 정보를 서버에서 지운다 (플레이 구독은 따로 해지해야 함) */
    suspend fun deleteAccount(): Boolean {
        val t = token ?: return false
        busy.value = true
        return try {
            post(JSONObject().put("action", "delete-account").put("token", t))
            clear()
            message.value = "계정을 지웠어요."
            true
        } catch (e: Exception) { message.value = e.message ?: "서버에 연결하지 못했어요."; false }
        finally { busy.value = false }
    }

    // 구독 (플레이 결제)
    internal suspend fun refreshPurchaseConfig(request: suspend (String) -> JSONObject = { t ->
        post(JSONObject().put("action", "iap-config").put("token", t))
    }): Boolean {
        _salesReady.value = false
        val t = token ?: run { accountToken = null; _purchaseNotice.value = "먼저 로그인해 주세요."; return false }
        return try {
            val j = request(t)
            if (token != t) { accountToken = null; _purchaseNotice.value = "로그인 계정이 바뀌었어요. 다시 눌러 주세요."; return false }
            accountToken = (j.opt("accountToken") as? String)?.takeIf { it.isNotBlank() }
            val google = j.optJSONObject("google")
            basePlans = google?.optJSONArray("basePlans")?.let { a ->
                (0 until a.length()).mapNotNull { i -> (a.opt(i) as? String)?.takeIf { it in setOf("month", "half", "year") } }.distinct()
            } ?: emptyList()
            val benefits = j.optJSONObject("plans")
            planBenefits = basePlans.mapNotNull { id ->
                val p = benefits?.optJSONObject(id) ?: return@mapNotNull null
                val cap = p.optInt("cap", 0); val months = p.optInt("months", 0)
                if (cap > 0 && months in listOf(1, 6, 12)) id to PlanBenefit(cap, months) else null
            }.toMap()
            // Missing, paused, or failed configuration must never open a purchase screen.
            _salesReady.value = SALES_ENABLED && j.opt("purchasesEnabled") == true &&
                j.opt("salesPaused") == false && accountToken != null && google?.optString("product") == "plus" && basePlans.isNotEmpty()
            _purchaseNotice.value = if (_salesReady.value) "" else j.optString("purchaseMessage").ifEmpty {
                if (accountToken == null) "계정 정보를 받지 못했어요. 잠시 후 다시 해 주세요." else SALES_NOTICE
            }
            true
        } catch (e: kotlinx.coroutines.CancellationException) { throw e }
        catch (e: Exception) {
            accountToken = null
            _purchaseNotice.value = e.message ?: "구독 판매 상태를 확인하지 못했어요. 잠시 후 다시 해 주세요."
            false
        }
    }

    suspend fun loadProducts() {
        refreshPurchaseConfig()
        PlusBilling.loadOffers(if (_salesReady.value) basePlans else emptyList())
    }

    internal fun canPurchaseFor(accountId: String): Boolean =
        SALES_ENABLED && _salesReady.value && token != null && accountToken == accountId

    suspend fun buy(activity: Activity, offer: PlusOffer) {
        if (busy.value) return
        if (!SALES_ENABLED) { message.value = SALES_NOTICE; return }
        val expectedToken = token ?: run { message.value = "먼저 로그인해 주세요."; return }
        busy.value = true
        message.value = ""
        try {
            loadProducts()
            if (token != expectedToken) { message.value = "로그인 계정이 바뀌었어요. 다시 눌러 주세요."; return }
            if (!_salesReady.value) { message.value = _purchaseNotice.value; return }
            val acc = accountToken ?: run { message.value = "계정 정보를 받지 못했어요. 잠시 후 다시 해 주세요."; return }
            PlusBilling.launch(activity, offer, acc)?.let { message.value = it }
        } finally { busy.value = false }
    }

    /**
     * 플레이 결제 토큰을 서버에 보내 구독 기간으로 바꾼다. 확인(acknowledge)은 서버가 한다.
     * 실패하면 확인하지 않고 둔다 → 다음 앱 실행 때 다시 보내고, 서버도 플레이 알림(RTDN)으로 다시 처리한다.
     */
    internal suspend fun sendPurchase(purchaseToken: String, verify: suspend (String, String) -> JSONObject = { login, receipt ->
        post(JSONObject().put("action", "iap-google").put("token", login).put("purchaseToken", receipt))
    }): Boolean {
        val t = token ?: return false
        return try {
            val response = verify(t, purchaseToken)
            if (token != t) return false
            if (response.opt("ok") != true) throw IllegalStateException("구매 확인이 완료되지 않았어요. 잠시 후 구매 복원을 다시 눌러 주세요.")
            apply(response)
            message.value = "✓ 쓰담 플러스가 시작됐어요. 컴퓨터 쓰담에서 같은 계정으로 로그인하세요."
            true
        } catch (e: Exception) { message.value = e.message ?: "서버에 연결하지 못했어요."; false }
    }

    suspend fun restore() {
        if (busy.value) return
        if (token == null) { message.value = "먼저 로그인해 주세요."; return }
        busy.value = true
        message.value = ""   // 지난 오류 문구가 남아 있지 않게
        try {
            // Account verification is still required, but salesPaused does not block restoration.
            if (!refreshPurchaseConfig() || accountToken == null) { message.value = _purchaseNotice.value; return }
            PlusBilling.resendPurchases(all = true); refresh()
            if (message.value.isEmpty() && !status.value.active) message.value = "복원할 구독이 없어요."
        } finally { busy.value = false }
    }
}

/** Compose 의 LocalContext 에서 액티비티 찾기 (구글 로그인 · 결제 화면에 필요) */
tailrec fun Context.findActivity(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> baseContext.findActivity()
    else -> null
}

/** 연결 탭의 쓰담 플러스 카드 */
@Composable
fun PlusCard() {
    val ctx = LocalContext.current
    // 로그인 폼이 계정 화면으로 바뀌어도 로그인 후 상품 조회를 마친다.
    val accountScope = rememberCoroutineScope()
    remember { Plus.init(ctx) }
    val loggedIn by Plus.loggedIn.collectAsStateWithLifecycle()
    val message by Plus.message.collectAsStateWithLifecycle()
    LaunchedEffect(Unit) { Plus.refresh(); Plus.loadProducts() }
    // 결제가 끝나면 카드를 안 보고 있어도 알 수 있게
    LaunchedEffect(message) { if (message.startsWith("✓ 쓰담 플러스")) Toast.makeText(ctx, message.removePrefix("✓ "), Toast.LENGTH_LONG).show() }

    Column(Modifier.fillMaxWidth().card(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("✨ 쓰담 플러스", fontWeight = FontWeight.Bold, color = T.lavender, fontSize = 17.sp)
        if (!Plus.SALES_ENABLED) Text(Plus.SALES_NOTICE, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
        Text("녹음과 기록은 무료예요. 쓰담 플러스는 컴퓨터에서 AI 정리와 초안을 만들 때 쓰며, 결제한 계정으로 컴퓨터 쓰담에 로그인하면 함께 적용돼요.",
            fontSize = 12.sp, color = T.soft)
        // 알림 문구는 위쪽에 (✓ 로 시작하면 성공 = 초록, 아니면 빨강)
        if (message.isNotEmpty()) Text(message, fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
            color = if (message.startsWith("✓")) T.mint else T.coral)
        if (loggedIn) PlusAccount() else PlusLogin(accountScope)
        Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            Text("이용약관", fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = T.blue,
                modifier = Modifier.padding(vertical = 4.dp).clickable { openUrl(ctx, Plus.TERMS_URL) })
            Text("개인정보 처리방침", fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = T.blue,
                modifier = Modifier.padding(vertical = 4.dp).clickable { openUrl(ctx, Plus.PRIVACY_URL) })
        }
    }
    // 처음 화면에 나올 때 끝나지 않은 결제를 서버로 (결제 라이브러리 연결 뒤)
    LaunchedEffect(loggedIn) { if (loggedIn) { Plus.loadProducts(); PlusBilling.resendPurchases() } }
}

@Composable
private fun PlusLogin(scope: kotlinx.coroutines.CoroutineScope) {
    val ctx = LocalContext.current
    val busy by Plus.busy.collectAsStateWithLifecycle()
    var mail by remember { mutableStateOf("") }
    var code by remember { mutableStateOf("") }
    var codeSent by remember { mutableStateOf(false) }
    var showEmail by remember { mutableStateOf(!Plus.googleEnabled) }
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        if (Plus.googleEnabled) {
            BigButton("G  구글로 로그인", Modifier.fillMaxWidth(), color = T.ink, enabled = !busy) {
                ctx.findActivity()?.let { a -> scope.launch { Plus.signInGoogle(a) } }
            }
            TextButton({ showEmail = !showEmail }) {
                Text(if (showEmail) "이메일 로그인 닫기" else "이메일 인증번호로 로그인", fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
            }
        }
        if (showEmail) {
            OutlinedTextField(mail, { mail = it }, Modifier.fillMaxWidth(), placeholder = { Text("이메일 주소") }, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email))
            if (codeSent) {
                OutlinedTextField(code, { code = it.filter(Char::isDigit).take(6) }, Modifier.fillMaxWidth(), placeholder = { Text("인증번호") },
                    singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    BigButton("로그인", enabled = code.isNotEmpty() && !busy) { scope.launch { Plus.verify(mail, code) } }
                    TextButton({ codeSent = false; code = "" }) { Text("다시 받기", fontSize = 13.sp) }
                }
            } else {
                ChipButton("인증번호 받기", if (mail.contains("@") && !busy) T.blue else T.soft, filled = true) {
                    if (mail.contains("@") && !busy) scope.launch { codeSent = Plus.sendCode(mail) }
                }
            }
        }
    }
}

@Composable
private fun PlusAccount() {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val email by Plus.email.collectAsStateWithLifecycle()
    val status by Plus.status.collectAsStateWithLifecycle()
    val busy by Plus.busy.collectAsStateWithLifecycle()
    val offers by PlusBilling.offers.collectAsStateWithLifecycle()
    val salesReady by Plus.salesReady.collectAsStateWithLifecycle()
    val purchaseNotice by Plus.purchaseNotice.collectAsStateWithLifecycle()
    var confirmDelete by remember { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(email ?: "", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = T.ink, modifier = Modifier.weight(1f))
            TextButton({ scope.launch { Plus.logout() } }, enabled = !busy) { Text("로그아웃", fontSize = 13.sp) }
        }
        if (status.active) Pill("✓ ${status.planName} · ${status.daysToEnd}일 남음", T.mint)
        else Text("지금은 구독 중이 아니에요.", fontSize = 13.sp, color = T.soft)
        if (PlusBilling.AVAILABLE) {
            if (!salesReady && purchaseNotice.isNotEmpty()) Text(purchaseNotice, fontSize = 12.sp, color = T.soft)
            (if (Plus.SALES_ENABLED && salesReady) offers else emptyList()).forEach { o ->
                Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp))
                    .then(if (busy) Modifier.background(Color.Gray.copy(alpha = 0.3f)) else Modifier.background(T.brand))
                    .clickable(enabled = !busy) { ctx.findActivity()?.let { a -> scope.launch { Plus.buy(a, o) } } }
                    .padding(horizontal = 16.dp, vertical = 11.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Text(o.title, fontSize = 15.sp, fontWeight = FontWeight.Bold, color = Color.White, modifier = Modifier.weight(1f))
                        Text(o.price, fontSize = 15.sp, fontWeight = FontWeight.Bold, color = Color.White)
                    }
                    o.periodMonths?.let { months ->
                        Text("${months}개월 총 ${o.price} · ${months}개월마다 자동 결제", fontSize = 12.sp, color = Color.White)
                        if (months > 1) o.monthlyEquivalent?.let { amount ->
                            Text("월 약 $amount (기간 총액을 나눈 금액)", fontSize = 12.sp, color = Color.White)
                        }
                    }
                    o.includedAiCount?.let { cap ->
                        Text("이용 기간 전체 AI 초안 ${java.text.NumberFormat.getIntegerInstance().format(cap)}회", fontSize = 12.sp, color = Color.White)
                    }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ChipButton("구독 관리") { openUrl(ctx, Plus.MANAGE_URL) }
                ChipButton("구매 복원", T.lavender) { if (!busy) scope.launch { Plus.restore() } }
            }
            Text("구글 플레이 계정으로 결제되고, 끄지 않으면 같은 기간으로 자동 갱신돼요. 플레이 스토어 → 프로필 → 결제 및 정기 결제 → 정기 결제에서 언제든 해지할 수 있어요.",
                fontSize = 11.sp, color = T.soft)
        } else {
            Text(Plus.STORE_PURCHASE_NOTICE + " 같은 계정으로 로그인하면 이용권을 함께 쓸 수 있어요. 구독 관리와 구매 복원은 구매한 스토어의 앱에서 해 주세요.",
                fontSize = 12.sp, color = T.soft)
        }
        // 계정 삭제 (스토어 정책: 앱 안에서 계정을 지울 수 있어야 함)
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
            TextButton({ confirmDelete = true }, enabled = !busy) { Text("계정 삭제", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = T.coral) }
        }
    }
    if (confirmDelete) ConfirmDialog("쓰담 플러스 계정을 지울까요?",
        "로그인 정보와 등록된 기기, 선생님 정보가 지워지고 되돌릴 수 없어요. 휴대폰과 컴퓨터에 있는 학생 기록은 그대로예요. Google Play 구독은 계정을 지워도 자동으로 해지되지 않으니, 먼저 ‘구독 관리’에서 해지해 주세요.",
        "계정 지우기", onDismiss = { confirmDelete = false }) { scope.launch { Plus.deleteAccount() } }
}
