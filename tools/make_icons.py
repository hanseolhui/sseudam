#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""쓰담 아이콘 · 로고 만들기 — 「웃는 쓰」 (ㅅㅅ 눈웃음 + ㅡ 웃는 입 + 볼 점).

    python3 tools/make_icons.py          # 기본 색(가: 남색 바탕 · 버터 웃음)으로 모든 플랫폼 파일을 다시 만든다
    python3 tools/make_icons.py 나       # 다른 색 조합으로

필요한 것(개발용 맥에만): rsvg-convert (brew install librsvg), Pillow.
앱 실행 코드는 이 스크립트를 쓰지 않는다.

만드는 파일
  macos/icon.svg · icon-full-1024.png(꽉 찬 원본, Assets.car 용) · icon-1024.png(둥근 판 + 그림자, icns · 윈도우 ico · MSIX 용)
  mobile/ios/…/AppIcon.appiconset/icon-1024(.png · -dark · -tinted), 워치 icon-1024.png
  mobile/android/…/mipmap-*/ic_launcher(.png · _foreground · _monochrome), drawable/ic_launcher_background.xml,
  mobile/android/store/icon-512.png · feature-graphic-1024x500.png(플레이 대표 이미지, Pretendard 글꼴 · OFL)
  app/static/icon-(192|512).png · icon-dark-(192|512).png, index.html 왼쪽 위 로고
  docs/brand/ (가로형 로고 · 글자 로고 SVG · PNG)
"""
import io
import os
import re
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CREAM, NAVY, NAVY2, BUTTER, BUTTER2, CORAL = "#FFF8F2", "#2E3A8C", "#4B58B5", "#FFE08A", "#FFD45C", "#FF8A73"
NIGHT, NIGHT2 = "#14172E", "#232A5C"

# 이름: (밝은 아이콘 (바탕, 선, 볼 점), 어두운 아이콘 (바탕, 선, 볼 점)) — 바탕이 (a, b) 면 왼쪽 위 → 오른쪽 아래 그라데이션
PALETTES = {
    "가": (((NAVY, NAVY2), BUTTER, CORAL), ((NIGHT, NIGHT2), BUTTER, CORAL)),
    "나": (((NAVY, NAVY2), CREAM, BUTTER2), ((NIGHT, NIGHT2), CREAM, BUTTER2)),
    "다": ((("#FFFBF6", "#FFEFE0"), NAVY, CORAL), ((NIGHT, NIGHT2), CREAM, CORAL)),
    "라": ((("#FF9A82", "#FF7A6B"), "#232B6B", BUTTER), ((NIGHT, NIGHT2), "#FF9A82", BUTTER)),
    "마": (((BUTTER, BUTTER), NAVY, CORAL), ((NIGHT, NIGHT2), BUTTER, CORAL)),
}
DEFAULT = "가"

# ---------------------------------------------------------------- 그림
# 1024 기준. 눈 두 개(ㅅㅅ), 입(ㅡ), 볼 점.
SMILE = ('<g fill="none" stroke="{fg}" stroke-width="92" stroke-linecap="round" stroke-linejoin="round">'
         '<path d="M216 458 L322 284 L428 458"/><path d="M556 458 L662 284 L768 458"/>'
         '<path d="M254 648 C370 778 614 778 730 648"/></g>'
         '<circle cx="844" cy="588" r="46" fill="{dot}"/>')
# 직접 그린 '쓰담' 글자 (폭 226 · 높이 100, 글꼴을 쓰지 않음)
WORD = ('<g fill="none" stroke="{fg}" stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M8 57 L27 12 L46 57"/><path d="M66 57 L85 12 L104 57"/><path d="M6 88 H106"/>'
        '<g transform="translate(126 0)"><path d="M50 12 H13 V46 H53"/><path d="M75 5 V55"/><path d="M75 29 H94"/>'
        '<path d="M19 68 H83 V94 H19 Z"/></g></g>')


def svg(inner, w=1024, h=1024):
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d">%s</svg>\n'
            % (w, h, w, h, inner))


def grad(bg, gid):
    return ('<linearGradient id="%s" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="%s"/>'
            '<stop offset="1" stop-color="%s"/></linearGradient>' % (gid, bg[0], bg[1]))


def full_svg(pal):
    """꽉 찬 정사각형 아이콘."""
    bg, fg, dot = pal
    return svg('<defs>%s</defs><rect width="1024" height="1024" fill="url(#bg)"/>%s'
               % (grad(bg, "bg"), SMILE.format(fg=fg, dot=dot)))


def mark_svg(fg, dot, scale=1.0, bg=None):
    """그림만 (투명 바탕, 가운데 기준으로 줄이기)."""
    back = '<rect width="1024" height="1024" fill="%s"/>' % bg if bg else ""
    return svg('%s<g transform="translate(512 512) scale(%s) translate(-512 -512)">%s</g>'
               % (back, scale, SMILE.format(fg=fg, dot=dot)))


def tile(pal, x, y, size, uid):
    """둥근 아이콘 조각 (다른 SVG 안에 넣을 때)."""
    bg, fg, dot = pal
    return ('<g transform="translate(%s %s) scale(%s)"><defs>%s<clipPath id="c%s"><rect width="1024" height="1024" rx="230"/></clipPath></defs>'
            '<g clip-path="url(#c%s)"><rect width="1024" height="1024" fill="url(#g%s)"/>%s</g></g>'
            % (x, y, round(size / 1024.0, 5), grad(bg, "g" + uid), uid, uid, uid, SMILE.format(fg=fg, dot=dot)))


def lockup_svg(pal, word, sub, page=None):
    """가로형 로고: 아이콘 + 쓰담 + 한 줄 소개."""
    W, H = 1300, 520
    back = '<rect width="%d" height="%d" fill="%s"/>' % (W, H, page) if page else ""
    return svg('%s%s<g transform="translate(520 112) scale(2.2)">%s</g>'
               '<text x="524" y="424" font-family="Apple SD Gothic Neo, Pretendard, sans-serif" font-weight="600" font-size="50" '
               'letter-spacing="1" fill="%s">말로 담고, 글로 씁니다</text>'
               % (back, tile(pal, 90, 90, 340, "L"), WORD.format(fg=word, sw=14.5), sub), W, H)


def wordmark_svg(fg):
    return svg('<g transform="translate(24 20) scale(4)">%s</g>' % WORD.format(fg=fg, sw=14.5), 952, 440)


def text_width(text, size, weight="SemiBold"):
    """Pretendard 로 쟀을 때의 글 너비 (글꼴이 없으면 어림값)."""
    try:
        from PIL import ImageFont
        f = ImageFont.truetype(os.path.expanduser("~/Library/Fonts/Pretendard-%s.ttf" % weight), size)
        return f.getlength(text)
    except Exception:
        return size * (len(text.replace(" ", "")) + 0.3 * text.count(" "))


def feature_svg(pal):
    """플레이 대표 이미지 1024×500: 왼쪽에 쓰담 글자 · 한 줄 소개, 오른쪽에 웃는 쓰."""
    bg, fg, dot = pal
    r, g, b = (int(bg[0][i:i + 2], 16) for i in (1, 3, 5))
    on_dark = (0.299 * r + 0.587 * g + 0.114 * b) < 150
    ink, veil = (CREAM, "#FFFFFF") if on_dark else (NAVY, NAVY)
    pill = "선생님의 학생 관찰 기록 도우미"
    pw = int(text_width(pill, 22) + 52)
    font = 'font-family="Pretendard, Apple SD Gothic Neo, sans-serif"'
    return svg(
        '<defs>%s</defs><rect width="1024" height="500" fill="url(#fbg)"/>'
        '<circle cx="790" cy="250" r="214" fill="%s" opacity="0.07"/>'
        '<circle cx="1000" cy="30" r="130" fill="%s" opacity="0.05"/>'
        '<circle cx="40" cy="500" r="120" fill="%s" opacity="0.05"/>'
        '<g transform="translate(84 80) scale(1.9)">%s</g>'
        '<text x="88" y="352" %s font-weight="700" font-size="38" fill="%s">말로 담고, 글로 씁니다</text>'
        '<rect x="84" y="384" width="%d" height="52" rx="26" fill="%s" opacity="0.14"/>'
        '<text x="110" y="418" %s font-weight="600" font-size="22" fill="%s">%s</text>'
        '<g transform="translate(525 -8) scale(0.5)">%s</g>'
        % (grad(bg, "fbg"), veil, veil, veil, WORD.format(fg=ink, sw=14.5), font, ink, pw, veil, font, ink, pill,
           SMILE.format(fg=fg, dot=dot)), 1024, 500)


def png(markup, size, mode="RGBA"):
    out = subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size), "-f", "png"],
                         input=markup.encode("utf-8"), stdout=subprocess.PIPE, check=True).stdout
    return Image.open(io.BytesIO(out)).convert(mode)


def png_wh(markup, width):
    out = subprocess.run(["rsvg-convert", "-w", str(width), "-f", "png"],
                         input=markup.encode("utf-8"), stdout=subprocess.PIPE, check=True).stdout
    return Image.open(io.BytesIO(out)).convert("RGBA")


def put(rel, im):
    p = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    im.save(p, optimize=True)
    print("  " + rel)


def put_text(rel, text):
    p = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)
    print("  " + rel)


def mac_tile(full):
    """맥 옛 형식(icns) · 윈도우용: 824 둥근 판 + 부드러운 그림자, 바깥은 투명."""
    S, T, R = 1024, 824, 185
    art = full.convert("RGBA").resize((T * 2, T * 2), Image.LANCZOS)
    mask = Image.new("L", (T * 2, T * 2), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, T * 2 - 1, T * 2 - 1], radius=R * 2, fill=255)
    art.putalpha(mask)
    art = art.resize((T, T), Image.LANCZOS)
    sh = Image.new("L", (S, S), 0)
    sh.paste(art.split()[3].point(lambda v: int(v * 0.26)), ((S - T) // 2, (S - T) // 2 + 12))
    sh = sh.filter(ImageFilter.GaussianBlur(14))
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(Image.new("RGBA", (S, S), (20, 22, 46, 255)), (0, 0), sh)
    out.alpha_composite(art, ((S - T) // 2, (S - T) // 2))
    return out


def main():
    key = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    if key not in PALETTES:
        sys.exit("색 조합은 %s 중 하나" % " · ".join(PALETTES))
    light, dark = PALETTES[key]
    print("색 조합 %s" % key)

    L = png(full_svg(light), 1024, "RGB")
    D = png(full_svg(dark), 1024, "RGB")

    # --- 맥 · 윈도우 (윈도우 ico · MSIX 묶음은 빌드 때 macos/icon-1024.png 에서 만든다)
    put_text("macos/icon.svg", full_svg(light))
    put("macos/icon-full-1024.png", L)
    put("macos/icon-1024.png", mac_tile(L))

    # --- 아이폰 · 워치
    ios = "mobile/ios/Sseudam/Assets.xcassets/AppIcon.appiconset/"
    put(ios + "icon-1024.png", L)
    put(ios + "icon-1024-dark.png", D)
    put(ios + "icon-1024-tinted.png", png(mark_svg("#FFFFFF", "#BDBDBD", bg="#000000"), 1024, "RGB"))
    put("mobile/ios/SseudamWatch/Assets.xcassets/AppIcon.appiconset/icon-1024.png", L)

    # --- 안드로이드 (적응형: 108dp 중 가운데 66dp 안에 그림)
    res = "mobile/android/app/src/main/res/"
    fg = mark_svg(light[1], light[2], 0.6)
    mono = mark_svg("#FFFFFF", "#FFFFFF", 0.6)
    for d, legacy, adaptive in (("mdpi", 48, 108), ("hdpi", 72, 162), ("xhdpi", 96, 216), ("xxhdpi", 144, 324), ("xxxhdpi", 192, 432)):
        put(res + "mipmap-%s/ic_launcher.png" % d, L.resize((legacy, legacy), Image.LANCZOS))
        put(res + "mipmap-%s/ic_launcher_foreground.png" % d, png(fg, adaptive))
        put(res + "mipmap-%s/ic_launcher_monochrome.png" % d, png(mono, adaptive))
    put_text(res + "drawable/ic_launcher_background.xml",
             '<?xml version="1.0" encoding="utf-8"?>\n'
             '<!-- 앱 아이콘 바탕 (tools/make_icons.py 가 만든다) -->\n'
             '<shape xmlns:android="http://schemas.android.com/apk/res/android" android:shape="rectangle">\n'
             '    <gradient android:type="linear" android:angle="315" android:startColor="%s" android:endColor="%s" />\n'
             '</shape>\n' % (light[0][0], light[0][1]))
    put_text(res + "values/ic_launcher_background.xml",
             '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <color name="ic_launcher_background">%s</color>\n</resources>\n'
             % light[0][0])
    put_text(res + "mipmap-anydpi-v26/ic_launcher.xml",
             '<?xml version="1.0" encoding="utf-8"?>\n'
             '<!-- 적응형 아이콘: 바탕 + 웃는 쓰(ㅅㅅ 눈웃음 · 웃는 입 · 볼 점), 테마 아이콘(단색) 지원 -->\n'
             '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
             '    <background android:drawable="@drawable/ic_launcher_background" />\n'
             '    <foreground android:drawable="@mipmap/ic_launcher_foreground" />\n'
             '    <monochrome android:drawable="@mipmap/ic_launcher_monochrome" />\n'
             '</adaptive-icon>\n')
    put("mobile/android/store/icon-512.png", L.resize((512, 512), Image.LANCZOS))
    put("mobile/android/store/feature-graphic-1024x500.png", png_wh(feature_svg(light), 1024).convert("RGB"))

    # --- 웹 (컴퓨터 앱 화면 · 브라우저 탭)
    for s in (192, 512):
        put("app/static/icon-%d.png" % s, L.resize((s, s), Image.LANCZOS).convert("RGBA"))
        put("app/static/icon-dark-%d.png" % s, D.resize((s, s), Image.LANCZOS).convert("RGBA"))
    inline = ('<svg class="mascot logo-mark" viewBox="0 0 1024 1024" aria-hidden="true" focusable="false">\n'
              '        <defs>%s</defs>\n'
              '        <rect width="1024" height="1024" rx="230" fill="url(#sd-logo-bg)"/>\n'
              '        %s\n'
              '      </svg>' % (grad(light[0], "sd-logo-bg"), SMILE.format(fg=light[1], dot=light[2])))
    p = os.path.join(ROOT, "app/static/index.html")
    html = open(p, encoding="utf-8").read()
    new, n = re.subn(r'<svg class="mascot logo-mark".*?</svg>', lambda m: inline, html, count=1, flags=re.S)
    if n == 1 and new != html:
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(new)
        print("  app/static/index.html (왼쪽 위 로고)")
    elif n != 1:
        print("  ! app/static/index.html 에서 로고 자리를 못 찾음")

    # --- 로고 묶음 (소개 페이지 · 문서 · 스토어 그림에 쓸 것)
    b = "docs/brand/"
    put_text(b + "icon.svg", full_svg(light))
    put_text(b + "icon-dark.svg", full_svg(dark))
    put_text(b + "logo.svg", lockup_svg(light, NAVY, "#6F6878"))
    put_text(b + "logo-dark.svg", lockup_svg(dark, "#F3F1EA", "#A9AEC8"))
    put_text(b + "wordmark.svg", wordmark_svg(NAVY))
    put_text(b + "wordmark-light.svg", wordmark_svg("#F3F1EA"))
    put(b + "icon-1024.png", L)
    put(b + "icon-dark-1024.png", D)
    put(b + "logo.png", png_wh(lockup_svg(light, NAVY, "#6F6878"), 2600))
    put(b + "logo-dark.png", png_wh(lockup_svg(dark, "#F3F1EA", "#A9AEC8"), 2600))
    put(b + "wordmark.png", png_wh(wordmark_svg(NAVY), 1904))
    put(b + "wordmark-light.png", png_wh(wordmark_svg("#F3F1EA"), 1904))
    print("끝")


if __name__ == "__main__":
    main()
