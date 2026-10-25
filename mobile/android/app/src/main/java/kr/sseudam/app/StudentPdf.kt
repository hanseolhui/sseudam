package kr.sseudam.app

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Typeface
import android.graphics.pdf.PdfDocument
import android.text.Layout
import android.text.StaticLayout
import android.text.TextPaint
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 학생 한 장 PDF (아이폰 StudentPDF 와 같은 구성): 이름·반·번호 → 초안(영역 · NEIS 바이트) → 날짜별 관찰 기록.
 * A4(595×842pt). 길면 여러 장으로 이어진다. cache/share 에 만들고 공유 시트로 보낸다.
 */
object StudentPdf {
    private const val W = 595
    private const val H = 842
    private const val M = 40f
    private val blue = 0xFF2E3A8C.toInt()
    private val ink = 0xFF1F2330.toInt()
    private val soft = 0xFF8A8F9C.toInt()
    private val line = 0xFFE3E5EA.toInt()

    private fun paint(size: Float, color: Int = ink, bold: Boolean = false) = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        textSize = size; this.color = color; typeface = if (bold) Typeface.DEFAULT_BOLD else Typeface.DEFAULT
    }

    private fun layout(text: String, p: TextPaint, width: Int): StaticLayout =
        StaticLayout.Builder.obtain(text, 0, text.length, p, width).setAlignment(Layout.Alignment.ALIGN_NORMAL)
            .setLineSpacing(2f, 1f).setIncludePad(false).build()

    fun make(ctx: Context, student: SStudent, cls: SClass?, notes: List<SNote>, drafts: List<SDraft>): File {
        val doc = PdfDocument()
        var pageNo = 0
        lateinit var page: PdfDocument.Page
        lateinit var c: Canvas
        var y = M
        val contentW = (W - 2 * M).toInt()

        fun newPage() {
            pageNo++
            page = doc.startPage(PdfDocument.PageInfo.Builder(W, H, pageNo).create())
            c = page.canvas
            y = M
            if (pageNo > 1) {   // 이어지는 장: 작은 머리말
                c.drawText("${student.displayName} · 이어서 ($pageNo)", M, y + 10f, paint(10f, soft))
                y += 24f
            }
        }
        fun ensure(h: Float) { if (y + h > H - M) { doc.finishPage(page); newPage() } }
        fun drawLayout(l: StaticLayout, x: Float) {
            c.save(); c.translate(x, y); l.draw(c); c.restore()
        }
        /** 긴 문단은 줄 단위로 나눠 장을 넘긴다 */
        fun paragraph(text: String, p: TextPaint, x: Float, width: Int, after: Float = 6f) {
            val l = layout(text, p, width)
            var start = 0
            while (start < l.lineCount) {
                ensure((l.getLineBottom(start) - l.getLineTop(start)).toFloat())
                var end = start
                while (end < l.lineCount && y + (l.getLineBottom(end) - l.getLineTop(start)) <= H - M) end++
                if (end == start) end = start + 1
                val sub = text.substring(l.getLineStart(start), l.getLineEnd(end - 1)).trimEnd('\n')
                val part = layout(sub, p, width)
                drawLayout(part, x); y += part.height
                start = end
                if (start < l.lineCount) { doc.finishPage(page); newPage() }
            }
            y += after
        }
        fun divider() { ensure(14f); y += 4f; c.drawLine(M, y, W - M, y, Paint().apply { color = line; strokeWidth = 1f }); y += 10f }

        newPage()
        // 머리말
        c.drawText(student.displayName, M, y + 24f, paint(24f, bold = true))
        val brand = paint(13f, blue, bold = true)
        c.drawText("쓰담", W - M - brand.measureText("쓰담"), y + 22f, brand)
        y += 34f
        val sub = listOfNotNull(cls?.title, student.number?.let { "${it}번" }).joinToString(" · ")
        if (sub.isNotEmpty()) { c.drawText(sub, M, y + 12f, paint(12f, soft)); y += 18f }
        c.drawText("만든 날 " + SimpleDateFormat("yyyy-MM-dd", Locale.KOREA).format(Date()), M, y + 11f, paint(10f, soft)); y += 16f
        divider()

        if (drafts.isNotEmpty()) {
            ensure(24f); c.drawText("초안", M, y + 14f, paint(14f, bold = true)); y += 24f
            for (d in drafts) {
                val text = d.content ?: ""
                val limit = Areas.limit(d.area)
                val b = neisBytes(text)
                ensure(16f)
                c.drawText("${Areas.name(d.area)} · ${b}/${limit}바이트" + if (b > limit) " (넘침)" else "", M, y + 10f,
                    paint(10f, if (b > limit) 0xFFFF8C7A.toInt() else soft, bold = true))
                y += 15f
                paragraph(text, paint(11.5f), M, contentW, 10f)
            }
            divider()
        }

        ensure(24f); c.drawText("관찰 기록 ${notes.size}개", M, y + 14f, paint(14f, bold = true)); y += 24f
        val dateW = 72f
        for (n in notes.sortedBy { it.date ?: "" }) {
            ensure(16f)
            c.drawText(n.date ?: "", M, y + 10f, paint(10f, soft, bold = true))
            paragraph(n.content ?: "", paint(11.5f), M + dateW, (contentW - dateW).toInt(), 8f)
        }
        if (notes.isEmpty()) paragraph("아직 기록이 없어요.", paint(11f, soft), M, contentW)

        doc.finishPage(page)
        val dir = File(ctx.cacheDir, "share").apply { mkdirs() }
        val safe = student.displayName.replace(Regex("""[\\/:*?"<>|]"""), "_")
        val f = File(dir, "쓰담_${safe}_" + SimpleDateFormat("yyyyMMdd", Locale.US).format(Date()) + ".pdf")
        f.outputStream().use { doc.writeTo(it) }
        doc.close()
        return f
    }
}
