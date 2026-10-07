#!/usr/bin/env python3
"""A game screen put together from the converted art, the way the Z80 does
it (planzx.md 2.2-2.3): each world row drawn into a row of pixels and a line
of attributes, sprites over it, and every character row of the screen
coloured by the world row that has most of its lines.

    tools/mockup.py build/mockup.png [--j 3]
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import zxart  # noqa: E402
import zxgfx  # noqa: E402

W = 24


class Row:
    def __init__(self):
        self.pix = [[0] * W for _ in range(8)]
        self.attr = [0x07] * W

    def tile(self, img, col, name=""):
        lines, attrs = zxgfx.tile(img, name)
        for y in range(8):
            for i, v in enumerate(lines[y]):
                self.pix[y][col + i] = v
        for i, a in enumerate(attrs[0]):
            self.attr[col + i] = a

    def sprite_slice(self, pairs, col, first_line, ink):
        """Lines first_line.. of a sprite into this row (8 lines at most)."""
        for y in range(8):
            sy = first_line + y
            if 0 <= sy < len(pairs):
                for i, (m, d) in enumerate(pairs[sy]):
                    self.pix[y][col + i] = (self.pix[y][col + i] & m) | d
        if ink is not None:
            for i in range(len(pairs[0])):
                self.attr[col + i] = (self.attr[col + i] & 0x38) | ink | (ink & 0x40)


def scene():
    """Rows bottom (0) to top: a list of (left, lanes x3, right, extras)."""
    T = zxart.track_tiles()
    U = zxart.side_tiles(zxart.URBAN_TILES)
    F = zxart.side_tiles(zxart.FOREST_TILES)
    B = zxart.bridge_rows()
    P = zxart.platform_tiles()
    S = {**zxart.item_sprites(), **zxart.scenery_sprites()}
    rows = []
    n = 26
    lanes = [["rail_a" if (r * 7 + l * 3) % 11 else "rail_b" for l in range(3)] for r in range(n)]
    # lane 1: a train, cab towards the runner from row 3
    seq = (["loco1_nose"] + ["loco1_body"] * 2 + ["loco1_pantograph"] + ["loco1_body"] * 6
           + ["loco1_pantograph", "wagon1_end_top", "wagon1_coupler", "wagon1_end_bottom"]
           + ["wagon1_body_a" if k % 3 == 1 else "wagon1_body_b" for k in range(9)])
    for i, t in enumerate(seq):
        if 3 + i < n:
            lanes[3 + i][1] = t
    # lane 2: a ramp up and a red train going away
    for k in range(3):
        lanes[5 + k][2] = "ramp_up_%d" % k
    seq2 = (["wagon3_end_bottom"] + ["wagon3_body_a" if k % 3 == 1 else "wagon3_body_b" for k in range(8)]
            + ["wagon3_end_top", "wagon3_coupler", "wagon3_end_bottom", "wagon3_body_b", "wagon3_body_a"])
    for i, t in enumerate(seq2):
        if 8 + i < n:
            lanes[8 + i][2] = t
    lanes[12][0], lanes[13][0] = "stop_0", "stop_1"
    lanes[19][0], lanes[20][0] = "signal_1", "signal_0"
    coins = {(1, 0), (3, 0), (5, 0), (7, 0), (9, 0), (15, 0), (17, 0)}
    for r in range(n):
        row = Row()
        if 21 <= r <= 23:
            name = ["footbridge_shadow", "footbridge_0", "footbridge_1"][r - 21]
            row.tile(B[name], 0, name)
            rows.append(row)
            continue
        forest = r >= 24
        if forest:
            left, right = F["ground_a"], F["ground_b_m"]
        elif r in (16, 17):
            left = U["road_cross_%d" % (r - 16)]
            right = U["road_cross_%d_m" % (r - 16)]
        else:
            left, right = U["road_a" if r & 1 else "road_b"], U["road_a_m" if r & 1 else "road_b_m"]
        row.tile(left, 0)
        row.tile(right, 18)
        for l in range(3):
            row.tile(T[lanes[r][l]], 6 + 4 * l, lanes[r][l])
        if 2 <= r <= 15:                    # a station's platform on the right
            kind = zxart.PLATFORM_SEQ[16 - r] if 16 - r < len(zxart.PLATFORM_SEQ) else None
            if kind:
                row.tile(P[kind + "_m"], 18, kind)
        for (cr, cl) in coins:
            if cr == r:
                pairs = zxgfx.sprite(S["coin0"], "coin0")
                row.sprite_slice(pairs, 6 + 4 * cl + 1, 0, zxgfx.ink_attr("Y"))
        rows.append(row)
    # overlays spanning rows: (sprite, column, bottom row)
    for name, col, bottom in (("car_red", 0, 1), ("taxi", 2, 4), ("bus", 4, 8), ("car_blue", 2, 12),
                              ("pu_turbo", 7, 10)):
        spr = S[name]
        pairs = zxgfx.sprite(spr, name)
        nrows = (spr.h + 7) // 8
        for k in range(nrows):
            r = bottom + nrows - 1 - k
            if r < n:
                rows[r].sprite_slice(pairs, col, k * 8, zxgfx.ink_attr(spr.ink))
    return rows


def compose(rows, top, j, runner=None):
    """Screen bytes (6912) of the picture whose top is row `top`, line j."""
    scr = bytearray(6912)
    for y in range(192):
        L = y + j
        r = top - (L >> 3)
        if 0 <= r < len(rows):
            line = rows[r].pix[L & 7]
            a = 0x4000 | ((y & 0xC0) << 5) | ((y & 7) << 8) | ((y & 0x38) << 2)
            scr[a - 0x4000:a - 0x4000 + W] = bytes(line)
    for cr in range(24):
        r = top - cr - (1 if j > 4 else 0)
        if 0 <= r < len(rows):
            scr[6144 + cr * 32:6144 + cr * 32 + W] = bytes(rows[r].attr)
        for c in range(W, 32):
            scr[6144 + cr * 32 + c] = 0x08 * 1 + 7          # the HUD: blue
    if runner:
        name, col, top_line = runner
        pairs = zxgfx.sprite(zxart.runner_sprites()[name], name)
        for dy, row in enumerate(pairs):
            y = top_line + dy
            a = ((y & 0xC0) << 5) | ((y & 7) << 8) | ((y & 0x38) << 2)
            for i, (m, d) in enumerate(row):
                scr[a + col + i] = (scr[a + col + i] & m) | d
    return scr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("png")
    ap.add_argument("--j", type=int, default=3)
    args = ap.parse_args()
    rows = scene()
    scr = compose(rows, 24, args.j, runner=("s1_run0", 7, 176 - 16))
    from zxrun import render
    render(bytes(scr), args.png, scale=3)
    print("wrote", args.png)


if __name__ == "__main__":
    main()
