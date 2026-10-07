#!/usr/bin/env python3
"""The tape's loading screen: the CPC's loading picture as a SCREEN$.

    tools/zxloadscr.py gfx/loading_art.jpg build/loading.scr [--png preview.png]

The CPC version's loading art (gfx/loading_art.jpg, copied from it) is
scaled to the Spectrum's 256x192 - to the width, cut at the bottom, so the
Acropolis stays - its colours made stronger, and every 8x8 cell gets the two
colours of one brightness that suit its pixels best, each pixel the nearer
of them (--dither: 4x4 ordered between them). Black goes with both
brightnesses, as on the machine. The art's own logo is covered with the
game's (tools/zxart.py logo(), as the menu shows it), centred at the top.
"""

import argparse
import sys

from PIL import Image

W, H = 256, 192
# the Spectrum's colours as emulators show them (normal, bright)
NORMAL = [(0, 0, 0), (0, 0, 215), (215, 0, 0), (215, 0, 215),
          (0, 215, 0), (0, 215, 215), (215, 215, 0), (215, 215, 215)]
BRIGHT = [(0, 0, 0), (0, 0, 255), (255, 0, 0), (255, 0, 255),
          (0, 255, 0), (0, 255, 255), (255, 255, 0), (255, 255, 255)]
BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]


def load(path):
    from PIL import ImageEnhance
    im = Image.open(path).convert("RGB")
    im = ImageEnhance.Color(im).enhance(1.6)
    im = ImageEnhance.Contrast(im).enhance(1.2)
    w, h = im.size
    nh = round(h * W / w)
    im = im.resize((W, nh), Image.LANCZOS)
    top = 0                                     # keep the top (the logo)
    if nh > H:
        top = min(nh - H, (nh - H) // 4)
    return im.crop((0, top, W, top + H)) if nh >= H else im


def fit(pixels, a, b):
    """(error, t list): each pixel's place between colours a and b."""
    ab = [b[i] - a[i] for i in range(3)]
    n2 = sum(v * v for v in ab) or 1
    err, ts = 0, []
    for p in pixels:
        ap = [p[i] - a[i] for i in range(3)]
        t = max(0.0, min(1.0, sum(ap[i] * ab[i] for i in range(3)) / n2))
        q = [a[i] + t * ab[i] for i in range(3)]
        err += sum((p[i] - q[i]) ** 2 for i in range(3))
        ts.append(t)
    return err, ts


def convert(im, dither=False):
    px = im.load()
    bitmap = [[0] * 32 for _ in range(H)]
    attrs = [[0] * 32 for _ in range(H // 8)]
    for cy in range(H // 8):
        for cx in range(32):
            cell = [px[cx * 8 + x, cy * 8 + y] for y in range(8) for x in range(8)]
            best = None
            for bright, pal in ((0, NORMAL), (1, BRIGHT)):
                for i in range(8):
                    for j in range(i, 8):
                        e, ts = fit(cell, pal[i], pal[j])
                        if best is None or e < best[0]:
                            best = (e, bright, i, j, ts)
            _, bright, paper, ink, ts = best
            for y in range(8):
                byte = 0
                for x in range(8):
                    t = ts[y * 8 + x]
                    limit = (BAYER[(cy * 8 + y) & 3][(cx * 8 + x) & 3] + 0.5) / 16 if dither else 0.5
                    if t > limit:
                        byte |= 0x80 >> x
                bitmap[cy * 8 + y][cx] = byte
            if paper == ink:                    # one colour: all paper
                for y in range(8):
                    bitmap[cy * 8 + y][cx] = 0
            attrs[cy][cx] = (0x40 if bright else 0) | (paper << 3) | ink
    return bitmap, attrs


LOGO_ROW = 0
SKY = 1                                 # the logo's paper: the sky's blue


def put_logo(bitmap, attrs):
    """The game's logo, its cells as zxgfx makes them, over the art's, on
    the sky's blue."""
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import zxart
    import zxgfx
    lines, cells = zxgfx.tile(zxart.logo(), "logo")
    col = (32 - len(lines[0])) // 2
    for y, row in enumerate(lines):
        bitmap[LOGO_ROW * 8 + y][col:col + len(row)] = row
    for cy, row in enumerate(cells):
        attrs[LOGO_ROW + cy][col:col + len(row)] = [(a & 0x47) | (SKY << 3) for a in row]


def scr_bytes(bitmap, attrs):
    out = bytearray(6912)
    for y in range(H):
        a = ((y & 0xC0) << 5) | ((y & 7) << 8) | ((y & 0x38) << 2)
        out[a:a + 32] = bytes(bitmap[y])
    for cy in range(24):
        out[6144 + cy * 32:6144 + cy * 32 + 32] = bytes(attrs[cy])
    return out


def preview(bitmap, attrs, path):
    im = Image.new("RGB", (W, H))
    p = im.load()
    for y in range(H):
        for cx in range(32):
            a = attrs[y // 8][cx]
            pal = BRIGHT if a & 0x40 else NORMAL
            for x in range(8):
                p[cx * 8 + x, y] = pal[a & 7] if bitmap[y][cx] & (0x80 >> x) else pal[(a >> 3) & 7]
    im.resize((W * 2, H * 2), Image.NEAREST).save(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("art")
    ap.add_argument("out")
    ap.add_argument("--png")
    ap.add_argument("--dither", action="store_true")
    args = ap.parse_args()
    bitmap, attrs = convert(load(args.art), args.dither)
    put_logo(bitmap, attrs)
    open(args.out, "wb").write(scr_bytes(bitmap, attrs))
    print("wrote %s" % args.out)
    if args.png:
        preview(bitmap, attrs, args.png)
        print("wrote %s" % args.png)
    return 0


if __name__ == "__main__":
    sys.exit(main())
