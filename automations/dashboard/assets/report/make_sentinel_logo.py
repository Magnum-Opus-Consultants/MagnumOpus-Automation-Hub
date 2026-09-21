"""Draw the Sentinel lockup used on the Up Management Report.

The mark is the same shield the app wears in the sidebar. That one is an SVG
in `frontend/src/components/Sidebar.tsx`; there is no SVG rasteriser in this
environment, so the geometry is re-drawn here with Pillow from the identical
32x32 path data. Keep the two in step: if the sidebar mark changes, change the
path constants below and re-run this script.

    python make_sentinel_logo.py

Writes `sentinel-logo.png` beside this file — the file the PDF renderer picks
up. It is committed, so the report builds on a machine without Pillow; the
script exists so the logo is regenerable rather than an unexplained binary.
"""
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'sentinel-logo.png')

# Rendered at 8x and downscaled, which is how you get clean edges out of
# Pillow's polygon fill - it has no antialiasing of its own.
SS = 8
W, H = 1200, 340

# Brand blue, top-left to bottom-right, as in the app's own gradient:
# blue-500 -> blue-600.
BRAND_FROM = (59, 130, 246)
BRAND_TO = (37, 99, 235)
# The wordmark takes the report template's own dk2 theme colour, so the lockup
# belongs to the document rather than sitting on top of it.
WORD = (68, 84, 106)

# The sidebar's shield path, viewBox 0 0 32 32:
#   M16 2.6 27 6.4v9.1c0 6.9-4.5 11.6-11 13.9-6.5-2.3-11-7-11-13.9V6.4L16 2.6Z
SHIELD = [
    ('M', (16, 2.6)),
    ('L', (27, 6.4)),
    ('L', (27, 15.5)),
    ('C', (27, 22.4), (22.5, 27.1), (16, 29.4)),
    ('C', (9.5, 27.1), (5, 22.4), (5, 15.5)),
    ('L', (5, 6.4)),
    ('L', (16, 2.6)),
]
# M10.2 17.6l3.3-3.6 2.7 2.6 4.4-5.2
CHECK = [(10.2, 17.6), (13.5, 14.0), (16.2, 16.6), (20.6, 11.4)]
CHECK_WIDTH = 2.1
DOT = (21.2, 11.2, 1.7)


def _bezier(p0, p1, p2, p3, steps=48):
    """Flatten one cubic segment to points."""
    out = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        out.append((
            u ** 3 * p0[0] + 3 * u * u * t * p1[0]
            + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
            u ** 3 * p0[1] + 3 * u * u * t * p1[1]
            + 3 * u * t * t * p2[1] + t ** 3 * p3[1],
        ))
    return out


def _shield_points(scale, dx, dy):
    pts, cur = [], None
    for seg in SHIELD:
        if seg[0] in ('M', 'L'):
            cur = seg[1]
            pts.append(cur)
        else:
            pts.extend(_bezier(cur, seg[1], seg[2], seg[3]))
            cur = seg[3]
    return [(x * scale + dx, y * scale + dy) for x, y in pts]


def _gradient(size, a, b):
    """A diagonal two-stop gradient, drawn a row at a time."""
    w, h = size
    img = Image.new('RGB', (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            t = (x / max(1, w - 1) + y / max(1, h - 1)) / 2
            px[x, y] = tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))
    return img


def build():
    w, h = W * SS, H * SS
    canvas = Image.new('RGBA', (w, h), (0, 0, 0, 0))

    # ── the shield ──
    mark_h = 260 * SS                      # the mark's height in the lockup
    scale = mark_h / 32.0
    dx, dy = 30 * SS, (H * SS - mark_h) / 2
    mask = Image.new('L', (w, h), 0)
    ImageDraw.Draw(mask).polygon(_shield_points(scale, dx, dy), fill=255)
    canvas.paste(_gradient((w, h), BRAND_FROM, BRAND_TO).convert('RGBA'),
                 (0, 0), mask)

    d = ImageDraw.Draw(canvas)

    # ── the check and the dot, in white on top ──
    line = [(x * scale + dx, y * scale + dy) for x, y in CHECK]
    d.line(line, fill=(255, 255, 255, 242),
           width=round(CHECK_WIDTH * scale), joint='curve')
    # Pillow's round caps only exist on joints, so cap the ends by hand.
    r = CHECK_WIDTH * scale / 2
    for x, y in (line[0], line[-1]):
        d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, 242))
    cx, cy, cr = DOT[0] * scale + dx, DOT[1] * scale + dy, DOT[2] * scale
    d.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], fill=(255, 255, 255, 255))

    # ── the wordmark, in the report's own face ──
    font = ImageFont.truetype(os.path.join(HERE, 'Carlito-Bold.ttf'),
                              size=round(150 * SS))
    text_x = dx + 32 * scale + 34 * SS
    box = d.textbbox((0, 0), 'Sentinel', font=font)
    d.text((text_x, (h - (box[3] - box[1])) / 2 - box[1]), 'Sentinel',
           font=font, fill=WORD + (255,))

    # Trim to the ink, then give it back a thin even margin: cropped flush to
    # the glyphs the wordmark's last letter reads as clipped.
    canvas = canvas.crop(canvas.getbbox())
    pad = round(canvas.height * 0.05)
    padded = Image.new('RGBA', (canvas.width + pad * 2, canvas.height + pad * 2),
                       (0, 0, 0, 0))
    padded.paste(canvas, (pad, pad))
    canvas = padded
    out = canvas.resize((round(canvas.width / SS), round(canvas.height / SS)),
                        Image.LANCZOS)
    out.save(OUT)
    print(f'{OUT}  {out.width} x {out.height}')
    return out.size


if __name__ == '__main__':
    build()
