"""Minimal installer artwork: native NSIS wizard, no simulated loading."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "build"
OUT.mkdir(parents=True, exist_ok=True)
DARK = "#272b33"
GREY = "#747d88"
WHITE = "#ffffff"
LINE = "#e6e9ee"


def font(size, bold=False):
    windows = Path(r"C:\Windows\Fonts")
    names = ("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf")
    for name in names:
        candidate = windows / name
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def symbol(draw, x, y, width, bg=DARK, fg=WHITE):
    radius = round(width * 0.23)
    draw.rounded_rectangle((x, y, x + width, y + width), radius=radius, fill=bg)
    arc = (x+width*.25, y+width*.22, x+width*.78, y+width*.79)
    draw.arc(arc, start=50, end=310, fill=fg, width=max(2, round(width*.085)))


icon = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
draw = ImageDraw.Draw(icon)
symbol(draw, 10, 10, 236)
icon.save(OUT / "central.ico", sizes=[
    (16,16), (24,24), (32,32), (48,48), (64,64), (128,128), (256,256)
])

sidebar = Image.new("RGB", (164, 314), WHITE)
draw = ImageDraw.Draw(sidebar)
draw.line((163, 0, 163, 313), fill=LINE, width=1)
symbol(draw, 28, 52, 55)
draw.text((28, 125), "Central", font=font(22, True), fill=DARK)
draw.text((28, 154), "Desktop", font=font(12), fill=GREY)
draw.line((28, 274, 135, 274), fill=LINE, width=1)
draw.text((28, 281), "Instalacao", font=font(11), fill=GREY)
sidebar.save(OUT / "installerSidebar.bmp")

header = Image.new("RGB", (150, 57), WHITE)
draw = ImageDraw.Draw(header)
symbol(draw, 111, 12, 31)
header.save(OUT / "installerHeader.bmp")
print(f"Arte do instalador pronta: {OUT}")
