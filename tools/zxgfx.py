#!/usr/bin/env python3
"""The art (tools/zxart.py) as the Spectrum's bytes: src/data/gfx.asm.

    tools/zxgfx.py              write src/data/gfx.asm
    tools/zxgfx.py --preview build/gfx.png    and draw every converted piece

A tile cell (8x8) becomes 8 bytes and an attribute: at most two colours, and
not bright and not-bright together (black goes with either). Which is the
paper: the first of the picture's `paper` letters found in the cell, else the
colour with more pixels. A cell of one colour is paper of it with the ink the
same. It fails, naming the piece, the cell and the colours, rather than
guess.

Sprites are masked, a (mask, data) pair a byte: screen = (screen AND mask)
OR data. Transparent pixels keep the screen (mask 1), ink and holes clear it
(mask 0) and ink sets it (data 1). Around every inked pixel the mask is also
cleared one pixel left and right, so a sprite keeps a dark outline wherever
it stands - unless the art says otherwise with a hole.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import zxart  # noqa: E402

COLOUR = {c: i for i, c in enumerate("kbrmgcyw")}
PALETTE = [
    (0x00, 0x00, 0x00), (0x00, 0x00, 0xD7), (0xD7, 0x00, 0x00), (0xD7, 0x00, 0xD7),
    (0x00, 0xD7, 0x00), (0x00, 0xD7, 0xD7), (0xD7, 0xD7, 0x00), (0xD7, 0xD7, 0xD7),
    (0x00, 0x00, 0x00), (0x00, 0x00, 0xFF), (0xFF, 0x00, 0x00), (0xFF, 0x00, 0xFF),
    (0x00, 0xFF, 0x00), (0x00, 0xFF, 0xFF), (0xFF, 0xFF, 0x00), (0xFF, 0xFF, 0xFF),
]


class ArtError(Exception):
    pass


def colour(ch):
    """letter -> (colour 0-7, bright 0/1/None for black)"""
    c = COLOUR[ch.lower()]
    if c == 0:
        return 0, None
    return c, 1 if ch.isupper() else 0


def cell(img, cx, cy, where):
    """bytes (8) and attribute of an 8x8 cell of a picture."""
    pix = [img.p[cy * 8 + y][cx * 8:cx * 8 + 8] for y in range(8)]
    count = {}
    for row in pix:
        for ch in row:
            count[ch] = count.get(ch, 0) + 1
    # one colour: letters that are the same colour count as one
    cols = {}
    bright = None
    for ch, n in count.items():
        c, b = colour(ch)
        cols[c] = cols.get(c, 0) + n
        if b is not None:
            if bright is not None and b != bright:
                raise ArtError("%s cell %d,%d: bright and not bright together (%s)"
                               % (where, cx, cy, "".join(sorted(count))))
            bright = b
    if len(cols) > 2:
        raise ArtError("%s cell %d,%d: %d colours (%s)"
                       % (where, cx, cy, len(cols), "".join(sorted(count))))
    order = sorted(cols, key=lambda c: -cols[c])
    paper = order[0]
    for ch in img.paper:
        if COLOUR[ch.lower()] in cols:
            paper = COLOUR[ch.lower()]
            break
    ink = [c for c in cols if c != paper]
    if not ink:                 # one colour: an ink that shows against it,
        ink = [7 if paper == 0 else 0]  # for what is drawn there later
        if paper == 0:
            bright = 1
    ink = ink[0]
    data = []
    for row in pix:
        v = 0
        for x, ch in enumerate(row):
            if COLOUR[ch.lower()] == ink and ink != paper:
                v |= 0x80 >> x
        data.append(v)
    attr = (0x40 if bright else 0) | (paper << 3) | ink
    return data, attr


def tile(img, where):
    """-> (lines: list of bytes rows, attrs: one row of cell attributes per
    cell row)"""
    if img.w % 8 or img.h % 8:
        raise ArtError("%s: %dx%d is not whole cells" % (where, img.w, img.h))
    cw, ch = img.w // 8, img.h // 8
    lines = [[0] * cw for _ in range(img.h)]
    attrs = [[0] * cw for _ in range(ch)]
    for cy in range(ch):
        for cx in range(cw):
            data, a = cell(img, cx, cy, where)
            attrs[cy][cx] = a
            for y in range(8):
                lines[cy * 8 + y][cx] = data[y]
    return lines, attrs


def sprite(spr, where):
    """-> list of rows of (mask, data) per byte"""
    out = []
    for r, row in enumerate(spr.rows):
        if any(ch not in ".Xo" for ch in row):
            raise ArtError("%s row %d: only . X o in a sprite" % (where, r))
        mask = [1] * spr.w
        data = [0] * spr.w
        for x, ch in enumerate(row):
            if ch == "X":
                data[x] = 1
                for dx in (-1, 0, 1):
                    if 0 <= x + dx < spr.w:
                        mask[x + dx] = 0
            elif ch == "o":
                mask[x] = 0
        pairs = []
        for b in range(spr.w // 8):
            m = d = 0
            for x in range(8):
                if mask[b * 8 + x]:
                    m |= 0x80 >> x
                if data[b * 8 + x]:
                    d |= 0x80 >> x
            pairs.append((m, d))
        out.append(pairs)
    return out


def ink_attr(ink):
    """A sprite's ink: the attribute bits it sets (ink + bright), or None."""
    if ink is None:
        return None
    c, b = colour(ink)
    return c | (0x40 if b else 0)


# ---------------------------------------------------------------------------
# Preview: the converted bytes drawn as the ULA would
# ---------------------------------------------------------------------------
def draw_tile(im, x0, y0, lines, attrs):
    for y, row in enumerate(lines):
        for cx, v in enumerate(row):
            a = attrs[y // 8][cx]
            ink, paper, br = a & 7, (a >> 3) & 7, 8 if a & 0x40 else 0
            for b in range(8):
                im.putpixel((x0 + cx * 8 + b, y0 + y),
                            PALETTE[(ink if v & (0x80 >> b) else paper) + br])


def draw_sprite(im, x0, y0, pairs, ink=None):
    for y, row in enumerate(pairs):
        for bx, (m, d) in enumerate(row):
            for b in range(8):
                bit = 0x80 >> b
                x = x0 + bx * 8 + b
                if d & bit:
                    im.putpixel((x, y0 + y), PALETTE[(ink & 7) + (8 if ink and ink & 0x40 else 0)]
                                if ink is not None else (255, 255, 255))
                elif not m & bit:
                    im.putpixel((x, y0 + y), (0, 0, 0))


def preview(path):
    from PIL import Image
    tiles = zxart.track_tiles()
    im = Image.new("RGB", (16 + 9 * 40, 16 + ((len(tiles) + 8) // 9) * 14), (60, 60, 60))
    for i, (name, t) in enumerate(tiles.items()):
        lines, attrs = tile(t, name)
        draw_tile(im, 8 + (i % 9) * 40, 8 + (i // 9) * 14, lines, attrs)
    im = im.resize((im.size[0] * 4, im.size[1] * 4), Image.NEAREST)
    im.save(path)
    print("wrote", path)


# ---------------------------------------------------------------------------
# src/data/gfx.asm
# ---------------------------------------------------------------------------
OUT = os.path.join(ROOT, "src", "data", "gfx.asm")
OUT_MENU = os.path.join(ROOT, "src", "data", "gfx_menu.asm")
OUT_HUD = os.path.join(ROOT, "src", "data", "gfx_hud.asm")


def ident(name):
    return name.upper().replace("-", "_")


class Asm:
    def __init__(self):
        self.lines = ["; generated by tools/zxgfx.py from tools/zxart.py - do not edit"]
        self.size = {}

    def emit(self, *lines):
        self.lines.extend(lines)

    def bytes_(self, values, per=16):
        for i in range(0, len(values), per):
            self.emit("                defb " + ",".join("#%02X" % v for v in values[i:i + per]))

    def tiles(self, asset, pieces):
        """A table of tiles: pixels line by line, then the attributes of each
        row of cells. IDX_<ASSET>_<NAME> by the order given."""
        start = len(self.lines)
        self.emit("gfx_%s_table:" % asset)
        for n in pieces:
            self.emit("                defw gfx_%s_%s" % (asset, n))
        total = 2 * len(pieces)
        for i, (n, img) in enumerate(pieces.items()):
            lines, attrs = tile(img, "%s %s" % (asset, n))
            self.emit("IDX_%s_%s equ %d" % (ident(asset), ident(n), i))
            self.emit("gfx_%s_%s:" % (asset, n))
            data = [v for row in lines for v in row] + [a for row in attrs for a in row]
            assert 0xFF not in [a for row in attrs for a in row]
            self.bytes_(data)
            total += len(data)
        w, h = next(iter(pieces.values())).w, next(iter(pieces.values())).h
        self.emit("GFX_%s_WIDTH equ %d" % (ident(asset), w // 8),
                  "GFX_%s_LINES equ %d" % (ident(asset), h),
                  "GFX_%s_COUNT equ %d" % (ident(asset), len(pieces)))
        self.size[asset] = total

    def sprites(self, asset, pieces, slices=False):
        """Masked: width (bytes), height (lines), ink attribute (#FF: none),
        then each line as a span: the bytes to skip at its left, how many
        are drawn, and those as (mask, data) pairs - a byte that leaves the
        picture as it is (mask #FF, data 0) is never drawn.

        slices: before each sprite, where its 8-line slices after the first
        start, from the sprite's address: slice k's at the sprite - 2k (the
        overlays, drawn a world row at a time: src/world.asm)."""
        self.emit("gfx_%s_table:" % asset)
        for n in pieces:
            self.emit("                defw gfx_%s_%s" % (asset, n))
        total = 2 * len(pieces)
        for i, (n, spr) in enumerate(pieces.items()):
            pairs = sprite(spr, "%s %s" % (asset, n))
            ink = ink_attr(spr.ink)
            data = [spr.w // 8, spr.h, 0xFF if ink is None else ink]
            starts = []
            for y, row in enumerate(pairs):
                if y % 8 == 0:
                    starts.append(len(data))
                used = [i for i, (m, d) in enumerate(row) if (m, d) != (0xFF, 0)]
                if not used:
                    data += [0, 0]
                    continue
                first, last = used[0], used[-1]
                data += [first, last - first + 1]
                data += [v for pair in row[first:last + 1] for v in pair]
            if slices:
                for k in range(len(starts) - 1, 0, -1):
                    self.emit("                defw %d" % starts[k])
                total += 2 * (len(starts) - 1)
            self.emit("IDX_%s_%s equ %d" % (ident(asset), ident(n), i))
            self.emit("gfx_%s_%s:" % (asset, n))
            self.bytes_(data)
            total += len(data)
        self.size[asset] = total


def mirrored_pairs(d):
    out = {}
    for n, v in d.items():
        out[n] = v
        out[n + "_m"] = v.mirrored()
    return out


def build():
    a = Asm()
    a.tiles("track", zxart.track_tiles())
    a.tiles("urban", zxart.side_tiles(zxart.URBAN_TILES))
    a.tiles("forest", zxart.side_tiles(zxart.FOREST_TILES))
    a.tiles("bridges", zxart.bridge_rows())
    a.tiles("platform", zxart.platform_tiles())
    # the kind of platform row by D_PLAT - 1 (#FF: none), src/world.asm
    a.emit("GFX_PLATFORM_SEQ_LEN equ %d" % len(zxart.PLATFORM_SEQ), "gfx_platform_seq:")
    a.bytes_([0xFF if k is None else zxart.PLATFORM_KINDS.index(k) for k in zxart.PLATFORM_SEQ])
    sc = zxart.scenery_sprites()
    a.sprites("urban_ov", mirrored_pairs({n: sc[n] for n in zxart.CARS}), slices=True)
    a.sprites("forest_ov", {n: sc[n] for n in zxart.TREES}, slices=True)
    a.sprites("items", zxart.item_sprites(), slices=True)
    a.sprites("player", zxart.runner_sprites())
    a.sprites("shadows", zxart.shadow_sprites())
    write(a, OUT)
    build_menu()


def write(a, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write("\n".join(a.lines) + "\n")
    for k, v in a.size.items():
        print("gfx  %-10s %5d bytes" % (k, v))
    print("gfx  total      %5d bytes -> %s" % (sum(a.size.values()), os.path.relpath(path, ROOT)))


def build_menu():
    """src/data/gfx_menu.asm: the font and the logo; src/data/gfx_hud.asm:
    the HUD's icons."""
    a = Asm()
    a.emit("gfx_font:                               ; 8 bytes a glyph (GLYPH_*)")
    total = 0
    for name, data in zxart.font_bytes():
        a.bytes_(data)
        total += len(data)
    a.size["font"] = total
    lines, attrs = tile(zxart.logo(), "logo")
    a.emit("GFX_LOGO_W equ %d" % len(lines[0]), "GFX_LOGO_H equ %d" % len(attrs),
           "gfx_logo:                               ; lines, then a row of attributes a cell row")
    data = [v for row in lines for v in row] + [v for row in attrs for v in row]
    a.bytes_(data)
    a.size["logo"] = len(data)
    write(a, OUT_MENU)
    a = Asm()
    total = 0
    for name, spr in zxart.hud_icons().items():
        rows = sprite(spr, "hud " + name)
        a.emit("HUD_INK_%s equ #%02X" % (ident(name), ink_attr(spr.ink)), "gfx_hud_%s:" % name)
        data = [d for (row,) in rows for (_, d) in [row]]
        a.bytes_(data)
        total += len(data)
    rail = [int(r.replace("X", "1").replace(".", "0"), 2) for r in zxart.HUD_RAIL]
    a.emit("gfx_hud_rail:")
    a.bytes_(rail)
    a.size["hud icons"] = total + len(rail)
    write(a, OUT_HUD)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preview", metavar="PNG")
    args = ap.parse_args()
    try:
        build()
        if args.preview:
            preview(args.preview)
    except ArtError as e:
        sys.exit("zxgfx: %s" % e)


if __name__ == "__main__":
    main()
