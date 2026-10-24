"""Play store graphics: 512x512 icon + 1024x500 feature graphic (Pretendard, OFL)."""
import os, sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = sys.argv[1]  # repo root
OUT = os.path.join(ROOT, "mobile/android/store")
FONTS = os.path.expanduser("~/Library/Fonts")
os.makedirs(OUT, exist_ok=True)


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


def gradient(w, h, c1, c2, diagonal=True):
    g = Image.new("RGB", (w, h))
    px = g.load()
    for y in range(h):
        for x in range(w):
            t = ((x / w) * 0.65 + (y / h) * 0.35) if diagonal else y / h
            px[x, y] = lerp(c1, c2, t)
    return g


# ---------- 512 icon: full-bleed (Play applies its own mask) ----------
mac = Image.open(os.path.join(ROOT, "macos/icon-1024.png")).convert("RGBA")
# mac 아이콘의 둥근 사각형(대략 100~924) 안쪽만 써서 꽉 찬 정사각형으로 (플레이가 모서리를 알아서 깎음)
R0, R1 = 100, 924
top = mac.getpixel((512, R0 + 12))[:3]
bot = mac.getpixel((512, R1 - 12))[:3]
S = 512
bg = gradient(S, S, top, bot, diagonal=False).convert("RGBA")
C0, C1 = 175, 865
k = S / (R1 - R0)
crop = mac.crop((C0, C0, C1, C1)).resize((int((C1 - C0) * k), int((C1 - C0) * k)), Image.LANCZOS)
pos = int((C0 - R0) * k)
# 가장자리를 부드럽게 섞기
fade = Image.new("L", crop.size, 0)
ImageDraw.Draw(fade).rounded_rectangle((6, 6, crop.width - 7, crop.height - 7), radius=40, fill=255)
fade = fade.filter(ImageFilter.GaussianBlur(6))
bg.paste(crop, (pos, pos), fade)
bg.convert("RGB").save(os.path.join(OUT, "icon-512.png"), optimize=True)

# ---------- 1024x500 feature graphic ----------
W, H, K = 1024, 500, 2  # draw at 2x then downscale
fg = gradient(W * K, H * K, (0x5B, 0x7C, 0xFA), (0x9B, 0x8C, 0xF5)).convert("RGBA")
d = ImageDraw.Draw(fg)

# soft bubbles in background
deco = Image.new("RGBA", fg.size, (0, 0, 0, 0))
dd = ImageDraw.Draw(deco)
for (cx, cy, r, a) in [(1900, 120, 210, 34), (1700, 900, 160, 26), (160, 920, 220, 22), (980, 70, 90, 30)]:
    dd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, a))
fg.alpha_composite(deco)

# mascot "Dami": speech-bubble face (same shapes as Theme.kt Dami())
def dami(size):
    m = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    md = ImageDraw.Draw(m)
    s = size
    body = gradient(s, int(s * 0.82), (0x5C, 0x7D, 0xFA), (0xA7, 0x8B, 0xFA)).convert("RGBA")
    mask = Image.new("L", body.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, body.width - 1, body.height - 1), radius=int(s * 0.36), fill=255)
    m.paste(body, (0, int(s * 0.09)), mask)
    md.polygon([(s * 0.2, s * 0.97), (s * 0.17, s * 0.78), (s * 0.42, s * 0.82)], fill=(0xA7, 0x8B, 0xFA, 255))
    w = int(s * 0.05)
    for x in (s * 0.39, s * 0.61):  # happy eyes
        md.arc((x - s * 0.06, s * 0.40, x + s * 0.06, s * 0.50), 200, 340, fill="white", width=w)
    for x in (s * 0.29, s * 0.71):  # cheeks
        r = s * 0.065
        md.ellipse((x - r, s * 0.6 - r, x + r, s * 0.6 + r), fill=(0xFF, 0x8C, 0x7A, 150))
    md.arc((s * 0.42, s * 0.53, s * 0.58, s * 0.66), 20, 160, fill="white", width=int(s * 0.045))
    return m

# white card behind mascot for contrast
card = Image.new("RGBA", fg.size, (0, 0, 0, 0))
cd = ImageDraw.Draw(card)
cx, cy, cr = 1560, 500, 300
cd.ellipse((cx - cr, cy - cr, cx + cr, cy + cr), fill=(255, 255, 255, 235))
shadow = card.filter(ImageFilter.GaussianBlur(30))
fg.alpha_composite(Image.eval(shadow, lambda v: v // 4) if False else shadow.point(lambda v: v // 3 if v else 0))
fg.alpha_composite(card)
m = dami(380)
fg.alpha_composite(m, (cx - 190, cy - 205))

# little speech bubble "말로 담고"
bub = Image.new("RGBA", fg.size, (0, 0, 0, 0))
bd = ImageDraw.Draw(bub)
bx, by = 1760, 150
bd.rounded_rectangle((bx, by, bx + 230, by + 110), radius=55, fill=(255, 209, 102, 255))
bd.polygon([(bx + 40, by + 100), (bx + 20, by + 160), (bx + 100, by + 105)], fill=(255, 209, 102, 255))
f_b = ImageFont.truetype(os.path.join(FONTS, "Pretendard-ExtraBold.ttf"), 50)
bd.text((bx + 115, by + 55), "♪ 말로!", font=f_b, fill=(0x1F, 0x23, 0x30), anchor="mm")
fg.alpha_composite(bub)

# text
f_title = ImageFont.truetype(os.path.join(FONTS, "Pretendard-Black.ttf"), 210)
f_sub = ImageFont.truetype(os.path.join(FONTS, "Pretendard-Bold.ttf"), 76)
f_small = ImageFont.truetype(os.path.join(FONTS, "Pretendard-SemiBold.ttf"), 40)
d = ImageDraw.Draw(fg)
d.text((120, 300), "쓰담", font=f_title, fill="white", anchor="ls")
d.text((126, 470), "말로 담고, 글로 씁니다", font=f_sub, fill="white", anchor="ls")
pill_t = "선생님의 학생 관찰 기록 도우미"
tw = d.textlength(pill_t, font=f_small)
pl = Image.new("RGBA", fg.size, (0, 0, 0, 0))
ImageDraw.Draw(pl).rounded_rectangle((120, 560, 120 + tw + 64, 640), radius=40, fill=(255, 255, 255, 60))
fg.alpha_composite(pl)
d = ImageDraw.Draw(fg)
d.text((152, 600), pill_t, font=f_small, fill="white", anchor="lm")

fg.convert("RGB").resize((W, H), Image.LANCZOS).save(os.path.join(OUT, "feature-graphic-1024x500.png"), optimize=True)
print("ok")
