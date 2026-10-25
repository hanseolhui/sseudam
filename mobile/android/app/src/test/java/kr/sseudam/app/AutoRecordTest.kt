package kr.sseudam.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** '말하면 담기' 판정기(AutoVad)를 가짜 dB 열로 확인 (프레임 100ms · 프레임 값 = 몇 번째 프레임인지) */
class AutoRecordTest {
    private class FakeSink : ClipSink<Int> {
        val begins = mutableListOf<List<Int>>()
        val written = mutableListOf<Int>()
        val ends = mutableListOf<Triple<Boolean, Long, Long>>()
        override fun begin(preRoll: List<Int>) { begins += preRoll }
        override fun write(frame: Int) { written += frame }
        override fun end(keep: Boolean, voicedMs: Long, clipMs: Long) { ends += Triple(keep, voicedMs, clipMs) }
    }

    private val sink = FakeSink()
    private val vad = AutoVad(AutoSens.NORMAL, 2500, sink)
    private var i = 0
    private fun feed(db: Float, ms: Int) = repeat(ms / 100) { vad.feed(db, i++) }

    @Test fun steadyNoiseNeverTriggers() {
        feed(-60f, 30_000)
        assertTrue(sink.begins.isEmpty())
        assertEquals(-60f, vad.floor!!, 0.01f)
        assertEquals(-45f, vad.threshold, 0.01f)   // max(−60+14, −45)
    }

    @Test fun loudAttackTriggersWithPreRoll() {
        feed(-60f, 3000)
        feed(-30f, 200)
        assertTrue("200ms 로는 아직 시작 안 함", sink.begins.isEmpty())
        feed(-30f, 100)
        assertEquals(1, sink.begins.size)
        val pre = sink.begins[0]
        assertEquals(13, pre.size)                     // 프리롤 1초(10) + 시작 확인 3프레임
        assertEquals((20..32).toList(), pre)           // 끊김 없이 이어진 프레임
        assertTrue(vad.capturing)
    }

    @Test fun silenceAfterSpeechStopsAndKeeps() {
        feed(-60f, 2000)
        feed(-30f, 3000)
        feed(-60f, 2400)
        assertTrue("아직 2.4초", sink.ends.isEmpty())
        feed(-60f, 100)
        assertEquals(1, sink.ends.size)
        val (keep, voiced, clip) = sink.ends[0]
        assertTrue(keep)
        assertEquals(3000L, voiced)
        assertEquals(1000L + 3000 + 2500, clip)        // 프리롤 + 말 + 멈춤 대기
        assertFalse(vad.capturing)
    }

    @Test fun backAboveThresholdResetsSilence() {
        feed(-60f, 2000)
        feed(-30f, 1500)
        feed(-60f, 2000)
        feed(-30f, 100)      // 다시 말함 → 조용함 0
        feed(-60f, 2000)
        assertTrue(sink.ends.isEmpty())
        feed(-60f, 500)
        assertEquals(1, sink.ends.size)
        assertEquals(1600L, sink.ends[0].second)
    }

    @Test fun hysteresisBandIsNeitherVoiceNorSilence() {
        feed(-60f, 2000)
        feed(-30f, 1500)
        feed(-46.5f, 10_000) // 문턱(−45)과 −48 사이: 조용함으로 세지 않음
        assertTrue(sink.ends.isEmpty())
        feed(-60f, 2500)
        assertEquals(1, sink.ends.size)
    }

    @Test fun shortBlipIsDiscarded() {
        feed(-60f, 2000)
        feed(-30f, 600)
        feed(-60f, 3000)
        assertEquals(1, sink.begins.size)
        assertEquals(1, sink.ends.size)
        assertFalse("600ms 는 기침·문소리로 보고 버림", sink.ends[0].first)
        assertEquals(600L, sink.ends[0].second)
    }

    @Test fun floorAdaptsFastDownSlowUp() {
        feed(-40f, 1000)
        assertEquals(-40f, vad.floor!!, 0.01f)
        feed(-60f, 2000)
        assertTrue("조용해지면 빨리 내려감", vad.floor!! < -57f)
        val before = vad.floor!!
        feed(-50f, 1000)    // 문턱 아래지만 바닥보다 큼 → 천천히
        assertTrue(vad.floor!! > before && vad.floor!! < before + 1f)
    }

    @Test fun stopDelayPresetsAndMaxClip() {
        vad.stopDelayMs = 1500
        feed(-60f, 2000)
        feed(-30f, 2000)
        feed(-60f, 1500)
        assertEquals(1, sink.ends.size)

        val s2 = FakeSink()
        val v2 = AutoVad(AutoSens.NORMAL, 2500, s2, maxClipMs = 5000)
        var k = 0
        repeat(20) { v2.feed(-60f, k++) }
        repeat(80) { v2.feed(-30f, k++) }   // 8초 계속 말함 → 5초에서 끊고 바로 이어 담음
        assertEquals(1, s2.ends.size)
        assertTrue(s2.ends[0].first)
        assertEquals(2, s2.begins.size)
        assertTrue(v2.capturing)
        v2.finish()
        assertEquals(2, s2.ends.size)
    }

    @Test fun finishSavesClipInProgress() {
        feed(-60f, 2000)
        feed(-30f, 1200)
        vad.finish()
        assertEquals(1, sink.ends.size)
        assertTrue(sink.ends[0].first)
    }

    @Test fun dbfsOfFullScaleAndSilence() {
        assertEquals(-100f, AutoRecorder.dbfs(ShortArray(1600)), 0.01f)
        val loud = ShortArray(1600) { if (it % 2 == 0) 16384 else -16384 }
        assertEquals(-6.02f, AutoRecorder.dbfs(loud), 0.05f)
    }
}
