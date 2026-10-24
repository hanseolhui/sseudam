package kr.sseudam.app

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File

/** 컴퓨터 쓰담(app/relay.py)과 똑같이 암호를 계산하는지 — 파이썬이 만든 덩어리를 열고, 내가 만든 걸 파일로 남겨 파이썬이 열어 봄 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class RelayTest {
    private val key = ByteArray(32) { it.toByte() }
    private val fromPython = "5353443184756d663cca937e5944f39cbd5a12df7c81db5700a7dfc80a389e25195d6630ce74c05e8c704555322831596e14c813c6a148ccec814ceedbb08716d3f6a4119cb68d707e2453d82f4d0b9f67a8322c2db55ce21d52ddf5d85a3a82f46673a05bb9f4f37bffc08c0469d0176c87c036cb94a81c6214e694636d73547a8e2f6a3770cc8c7e2ad76210e2c99468924ecd985e9bff13d84e83d9c6df020a9fc8bf026c8e1aa9c8a57f384930227d0b9a46cead8b26d078c30b5ca10fb60ef711257fbc1a6a3690b34623d94df16e944c3c6328f86efdaac20cf94727f2b8ed98b9c2dcdf1571b957d7113f55e20c0a7fd91bbd6a96ba25e5d01eb37ff728fc364fd8c9700acd2136ecb667d0f68d38ede508985296ac0f7daeaf8b5b1d296f6d05ae4bb8f38c98d56fc5273117d97683224a0c3f2adc442d941d56ff126133e35b10c99f206a75609c262a2c46e6d4c025276d41d24742c9aedb1d9c42938ff0ee11158872634038efe634612ef17bb58373e226050d15bfaab6b84fabd8184acc73f13bd14af1404441d4b3b514943c7eaf48ae45306d33d311d387057eedc3999684fe78f3c840b6a0f3fca90628eb17129fecd2f82b22b9f1a8f08f09d6ddbf7202754b19bcf9317db9dfd23dc7700110db072fb17e1a3774e3b42a854879e1be7d74adb74b4deb15ddaf0c7b747c56f3e4aecd3ce25b49e2f2918f405e6c75a392d3f217b14d579c34d6c4df3b542f2077bd53d1c22e34b214de82ef737d2a3aba6082dcd4b7db882d9d42948d566a133578dfcef2edf5b809a1bf6481022ffea3a76e4792b369bc4e6862d1aec86c7d54a4b5a2540ef65f9249d239ebace1199e0b4c03f5e3f211db8d684a45cb615b644d9e3b6e0db4ac539b464b99da00691c4e2047cc07c7ba383f1dd9a4c1e393f8ad363216db90060325202150eb6b5c1e28fc9b2c4534192d7edb0968be9b784f8a868df15b9fdbc0e039ef425e67fee8dbbea6ef40e7c3f0c16babf6694b88cc7fbdadc8897c5bc2e827bd85a3d5575a7380f55ec3f3d2da9fe5352af59da1ed3b0803e09afeabec69488f4bbe4480e89ff8762980a133671d65ac0e3828169c318f4f2aec760dd4b025dc587541ff7b5b2ab8c9619094bfa039f819918add76af7a6f842a5e2bd4a8c88eb005d71a7477ac9fd6fb41d3d22290b8c63e4ea637e2c9ad2b6b4f9bba7c838dd9a77dca11c3900f15fedf6e5485b5137ee29bece36ed4fdbd5a42abb4c5d76ebd5d8cc712f2ccf9ad2ff865f1d01ae24d70c6bea537e902d4b592b89882a394b064bf0002ba05831db5364342b05ecdae5d454c98844c9a800bd47f62fe5891d9e924d4c0470e056b1d27d5ef6a680e98ca4fb93e0d89e4e5f5993c613af9e0e65348bb6e40ad1df8a154209c79535f4b23af38cf855ab80bcfbcc3c335f62b48f6b9ac5d620ba62f37d348770b62d43ce8807c02e6f6fcae951dfd9156c4beb75d7e0021186771c22189dac2468a359a943cbbed56ed7857030a440c6536831629a9d92514de9b4e3d08744bb3ac9346a8905da18a04dd46bb727d5169b7c9f2723fd602d1342bf97a3f03c7b788124ff8faa18e2759ce7eaea5e9ad53dfb07b51c0ff3c7c09fbc0f8745edd97ba87deac1e170e55e9bac4c84620703a31b974b776142c4376d1f6adddc73693fe4ed6f0acf1a41e9d1367ed9faf3b04791c80cd9d84b63af8d9cce132437aec2528d64cd91b5a283d4c5ff77f83e50c080bce783689ee106db15c5adc9cf206e15d201201965444a8817dee4884bb8d5b984b16e8697a3a0a43d996351b90413ce1da07c809902fc750b6d44d76702bf9d3b16dff0c95b8cb38064171f37a3ecb62b803185bc9d2ddfc8bd8e0724c7778e96af2616cf24b1dc139d1346cedb583aa61f1a2e083410b3a58539b411162088fab82116e8ea453464270e76c1ad4a5bfaf21dc1a5cead331ccca291268c2b757ac313d762b784e90e2452487e0ad2237d2685318096eca8d66d475419013f6c12b8195932cad032c477672b90fb1b6671e21c35e06b183c143a139827da19e6adcd877efd3998061b29f3c36aadced70fc73bfee0cb33beb93098bc31eb95399471f11af0d45699e77a149a9de292003ed4a2fef3afc88b7f6b924792b4ededfe7cc4d0ab1f2d940f299c8c8d837ec177bb9ebbec4ff5c26cb1664ea5a0a6bad3bcaed1820c5ddb7aece2e46f560a83312f5478d5608e60690a45179e4fb655a789af8aad370d14738d61f4ec6e2800f366e5fc61ea129dcc76b133af15c54f8f999b6a7a39d182f702dd5700eb8a9a49a2cafbde5a8b992f74b0caea6235648ed46b32da1fdd4e14e67e7cd29a99293fa78931fdf8a25cc178208d34be0286b40e0823cf13e1c04648a2ab4f4f8979483d8486a877d98ced7388bfd7edb6452197a1c14ea5917279e91853c3611e7eef4afcd693b399fc9cdb5500c895519b27b0652a1f647cb66b009c110ab720d70c904b919e00ed90d8df8fa3acb94753c0c26acc8cfdebdd42d5ac4924cee6fb983a084bb771d2eb9a73805c4c25a38388d73fdb0566f017cf81066e0"

    private fun unhex(s: String) = ByteArray(s.length / 2) { s.substring(it * 2, it * 2 + 2).toInt(16).toByte() }

    @Test fun opensBlobMadeByMac() {
        val (meta, body) = Relay.open(key, unhex(fromPython))
        assertEquals("rec", meta.getString("type"))
        assertEquals("테스트 녹음.m4a", meta.getString("name"))
        assertEquals("hello-audio-bytes".repeat(100), String(body))
    }

    @Test fun sealsBlobForMac() {
        val blob = Relay.seal(key, JSONObject().put("type", "rec").put("name", "안드로이드.m4a"), "android-bytes".repeat(500).toByteArray())
        val (meta, body) = Relay.open(key, blob)
        assertEquals("안드로이드.m4a", meta.getString("name"))
        assertTrue(String(body).startsWith("android-bytes"))
        File(System.getProperty("java.io.tmpdir"), "sseudam_android_blob.hex").writeText(blob.joinToString("") { "%02x".format(it) })
    }

    @Test fun parsesComputerQr() {
        val p = Relay.parse("sseudam://pair?v=1&u=https%3A%2F%2Fsseudam-relay.hanseolhui.workers.dev&c=0123456789abcdef0123456789abcdef&k=AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8&n=%EA%B9%80%EC%93%B0%EB%8B%B4")!!
        assertEquals("https://sseudam-relay.hanseolhui.workers.dev", p.url)
        assertEquals("김쓰담", p.name)
        assertTrue(p.key.contentEquals(key))
    }
}
