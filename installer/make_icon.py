"""Generate installer/app.ico — a lens over a mini bar-chart, on the app's dark
theme (bg #0d1117, accent #58a6ff, in #3fb950). Multi-size .ico for Windows."""
import math
from PIL import Image, ImageDraw

S = 1024  # supersample, then downscale for smooth edges
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

def rr(box, r, fill):
    d.rounded_rectangle(box, radius=r, fill=fill)

# rounded dark tile
m = int(S * 0.06)
rr((m, m, S - m, S - m), int(S * 0.20), (13, 17, 23, 255))         # --bg
rr((m, m, S - m, S - m), int(S * 0.20), None)
# subtle inner panel
pm = int(S * 0.14)
rr((pm, pm, S - pm, S - pm), int(S * 0.15), (22, 27, 34, 255))     # --panel

# mini bar chart inside the lens area
bars = [(0.34, 0.30, (63, 185, 80)),    # green  --in
        (0.46, 0.44, (88, 166, 255)),   # blue   --accent
        (0.58, 0.58, (210, 153, 34))]   # amber  --net
base = 0.66
bw = 0.09 * S
for cx, h, col in bars:
    x = cx * S
    top = (base - h) * S
    d.rounded_rectangle((x, top, x + bw, base * S), radius=int(bw * 0.25),
                        fill=col + (255,))

# magnifying-glass ring + handle in accent blue
cx, cy, rad = 0.50 * S, 0.47 * S, 0.30 * S
lw = int(S * 0.055)
d.ellipse((cx - rad, cy - rad, cx + rad, cy + rad), outline=(88, 166, 255, 255),
          width=lw)
# handle
a = math.radians(45)
hx, hy = cx + rad * math.cos(a), cy + rad * math.sin(a)
ex, ey = cx + (rad + 0.20 * S) * math.cos(a), cy + (rad + 0.20 * S) * math.sin(a)
d.line((hx, hy, ex, ey), fill=(88, 166, 255, 255), width=int(lw * 1.15))
d.ellipse((ex - lw * 0.55, ey - lw * 0.55, ex + lw * 0.55, ey + lw * 0.55),
          fill=(88, 166, 255, 255))

img = img.resize((256, 256), Image.LANCZOS)
img.save("installer/app.ico",
         sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                (128, 128), (256, 256)])
print("wrote installer/app.ico")
