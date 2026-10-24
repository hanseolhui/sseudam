"""스토어 묶음용 아이콘 PNG 만들기: python make_assets.py <원본 1024 png> <Assets 폴더>"""
import os
import sys

from PIL import Image

src, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
icon = Image.open(src).convert("RGBA")


def square(name, size, pad=0.0):
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    inner = int(size * (1 - pad * 2))
    canvas.paste(icon.resize((inner, inner), Image.LANCZOS), ((size - inner) // 2, (size - inner) // 2))
    canvas.save(os.path.join(out, name))


square("StoreLogo.png", 50)
square("Square44x44Logo.png", 44)
square("Square44x44Logo.targetsize-44_altform-unplated.png", 44)
square("Square150x150Logo.png", 150, pad=0.12)
wide = Image.new("RGBA", (310, 150), (0, 0, 0, 0))
wide.paste(icon.resize((120, 120), Image.LANCZOS), (95, 15))
wide.save(os.path.join(out, "Wide310x150Logo.png"))
print("assets ok:", sorted(os.listdir(out)))
