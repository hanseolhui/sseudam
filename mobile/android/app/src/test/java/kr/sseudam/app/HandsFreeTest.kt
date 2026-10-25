package kr.sseudam.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** 손 없이 녹음 '말을 멈추면 저절로 끝' 판정(EndDetector)을 가짜 dB 열로 확인 (0.1초마다 하나) */
class HandsFreeTest {
    private val d = EndDetector(2500)
    private var t = 0
    /** ms 동안 같은 크기를 넣고, 끝내라고 한 첫 시각(ms)을 돌려줌 (없으면 -1) */
    private fun feed(db: Float, ms: Int): Int {
        var stopAt = -1
        repeat(ms / 100) { t += 100; if (d.feed(db) && stopAt < 0) stopAt = t }
        return stopAt
    }

    @Test fun floorIsQuietestOfFirstHalfSecond() {
        d.feed(-100f)                       // 첫 읽기 0 (무음) 은 빼고
        listOf(-55f, -62f, -58f, -60f).forEach { d.feed(it) }
        assertEquals(-62f, d.floor!!, 0.01f)
        assertEquals(-48f, d.threshold, 0.01f)   // max(−62+12, −48)
    }

    @Test fun noisyRoomRaisesThreshold() {
        feed(-45f, 500)
        assertEquals(-33f, d.threshold, 0.01f)
    }

    @Test fun speechThenSilenceStopsAfterDelay() {
        feed(-60f, 500)
        assertEquals(-1, feed(-30f, 3000))
        assertTrue(d.spoke)
        assertEquals(-1, feed(-60f, 2400))
        assertTrue("2.5초 조용하면 끝", feed(-60f, 100) > 0)
    }

    @Test fun stopsExactlyWhenSilenceReachesDelay() {
        feed(-60f, 500)
        feed(-30f, 2000)
        val stop = feed(-60f, 5000)
        assertEquals(500 + 2000 + 2500, stop)
    }

    @Test fun stopDelayPresets() {
        listOf(1500L, 4000L).forEach { delay ->
            val e = EndDetector(delay)
            repeat(5) { e.feed(-60f) }
            repeat(20) { e.feed(-30f) }
            var n = 0
            while (!e.feed(-60f)) n++
            assertEquals(delay / 100 - 1, n.toLong())
        }
    }

    @Test fun voiceAgainResetsSilence() {
        feed(-60f, 500)
        feed(-30f, 1000)
        assertEquals(-1, feed(-60f, 2000))
        feed(-30f, 100)
        assertEquals(-1, feed(-60f, 2400))
        assertTrue(feed(-60f, 100) > 0)
    }

    @Test fun hysteresisBandDoesNotCountAsSilence() {
        feed(-60f, 500)
        feed(-30f, 1000)
        assertEquals(-1, feed(-49.5f, 10_000))   // 문턱(−48)과 −51 사이
        assertTrue(feed(-60f, 2500) > 0)
    }

    @Test fun noSpeechEndsAfterEightSeconds() {
        assertEquals(8000, feed(-60f, 10_000))
        assertFalse(d.spoke)
    }

    @Test fun shortBlipIsNotSpeech() {
        feed(-60f, 500)
        feed(-30f, 200)                     // 0.2초는 '말함' 아님
        assertFalse(d.spoke)
        assertEquals(8000, feed(-60f, 10_000))
    }

    @Test fun ampToDbfs() {
        assertEquals(-100f, EndDetector.dbfs(0), 0.01f)
        assertEquals(0f, EndDetector.dbfs(32767), 0.01f)
        assertEquals(-6.02f, EndDetector.dbfs(16384), 0.02f)
    }
}
