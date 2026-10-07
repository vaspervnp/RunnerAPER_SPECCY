#!/usr/bin/env python3
"""The world on the screen against its descriptors (planzx.md 2.2-2.3).

    tools/worldcheck.py build/runner.bin build/runner.sym [--frames N] [--speed S]

After a blit, every world row whose eight lines are all on the screen is
taken off it and compared with the tiles its descriptor names, converted
here from tools/zxart.py by tools/zxgfx.py: the bridge rows whole, and in
the others the sides and the lanes - all of them in a row no overlay was
drawn into (D_FLAGS bit 6), and only the lanes' outer cells in the rest
(items and scenery lie over the others). And each character row's
attributes against the attribute line of the world row that has most of
its lines. Then the generator's rules over the rows it made: one lane always
open from the ground, at least.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from zxrun import Machine, line_addr  # noqa: E402
import zxart  # noqa: E402
import zxgfx  # noqa: E402

W = 24
ROW_SIZE = 16


def tiles(pieces):
    return [zxgfx.tile(img, n) for n, img in pieces.items()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("binary")
    ap.add_argument("sym")
    ap.add_argument("--frames", type=int, default=600)
    ap.add_argument("--speed", type=int, default=6)
    ap.add_argument("--skill", type=int, default=0)
    args = ap.parse_args()
    track = tiles(zxart.track_tiles())
    urban = tiles(zxart.side_tiles(zxart.URBAN_TILES))
    forest = tiles(zxart.side_tiles(zxart.FOREST_TILES))
    bridges = tiles(zxart.bridge_rows())
    plat = tiles(zxart.platform_tiles())
    seq = [None if k is None else zxart.PLATFORM_KINDS.index(k) for k in zxart.PLATFORM_SEQ]

    m = Machine(args.binary, args.sym)
    m.poke("scroll_speed", args.speed)
    m.poke("skill", args.skill)
    ring = m.addr("world_ring")
    stats = {"rows": 0, "whole": 0, "lanes": 0, "attrs": 0, "bridges": 0, "plat": 0}
    fails = []

    def desc(row):
        a = ring + (row & 63) * ROW_SIZE
        return m.mem[a:a + ROW_SIZE]

    def check(mm):
        top, j = mm.peekw("cur_top_row"), mm.peek("cur_j")
        first = 1 if j else 0          # the top row shows whole only when j = 0
        for k in range(first, 25):
            row = top - k
            y0 = k * 8 - j
            if y0 < 0 or y0 + 8 > 192:
                continue
            d = desc(row)
            if d[0] & 0x20:
                continue                # a name written over it (src/text.asm)
            shown = [bytes(mm.mem[line_addr(y0 + y):line_addr(y0 + y) + W]) for y in range(8)]
            want = [[None] * W for _ in range(8)]

            def put(t, col, cells=None):
                lines, _ = t
                for y in range(8):
                    for i, v in enumerate(lines[y]):
                        if cells is None or i in cells:
                            want[y][col + i] = v
            overlay = d[0] & 0x40
            if d[0] & 0x80:
                put(bridges[d[1]], 0)
                stats["bridges"] += 1
            else:
                sides = forest if d[0] & 1 else urban
                if not overlay:
                    put(sides[d[1]], 0)
                    put(sides[d[2]], 18)
                    if d[12]:
                        kind = seq[d[12] - 1]
                        if kind is not None:
                            put(plat[2 * kind], 3)
                            put(plat[2 * kind + 1], 18)
                            stats["plat"] += 1
                for lane in range(3):
                    put(track[d[3 + lane]], 6 + 4 * lane, None if not overlay else (0, 3))
            for y in range(8):
                for x in range(W):
                    if want[y][x] is not None and want[y][x] != shown[y][x]:
                        fails.append("frame %d row %d (top %d j %d) line %d column %d: %02X, "
                                     "the descriptor says %02X (flags %02X)"
                                     % (mm.frame, row, top, j, y, x, shown[y][x], want[y][x], d[0]))
                        return
            stats["rows"] += 1
            stats["whole" if not overlay else "lanes"] += 1
        # attributes: character row cr from world row top - cr (- 1 if j > 4)
        for cr in range(24):
            row = top - cr - (1 if j > 4 else 0)
            d = desc(row)
            got = bytes(mm.mem[0x5800 + cr * 32:0x5800 + cr * 32 + W])
            if d[0] & 0x60:
                continue                # an overlay's ink is in some cells
            if d[0] & 0x80:
                want = bridges[d[1]][1][0]
            else:
                sides = forest if d[0] & 1 else urban
                want = sides[d[1]][1][0] + [a for lane in range(3) for a in track[d[3 + lane]][1][0]] \
                    + sides[d[2]][1][0]
                if d[12] and seq[d[12] - 1] is not None:
                    kind = seq[d[12] - 1]
                    want[3:6] = plat[2 * kind][1][0]
                    want[18:21] = plat[2 * kind + 1][1][0]
            if list(got) != list(want):
                fails.append("frame %d character row %d (world row %d): attributes %s, want %s"
                             % (mm.frame, cr, row, got.hex(), bytes(want).hex()))
                return
            stats["attrs"] += 1

    def no_sprites(mm):                 # the screen without the runner and coins
        mm.poke("spr_count", 0)
    m.on_pc("blit", no_sprites)
    m.on_pc("after_blit", check)
    m.run_frames(args.frames)
    print("    %d rows checked on the screen (%d whole, %d by their lanes' edges, "
          "%d bridge rows, %d with a platform), %d attribute rows"
          % (stats["rows"], stats["whole"], stats["lanes"], stats["bridges"], stats["plat"],
             stats["attrs"]))
    # the generator's rows: one lane open from the ground in every row
    top = m.peekw("cur_top_row")
    blocked = []
    for row in range(max(0, top - 60), top + 1):
        d = desc(row)
        if not any((d[6 + lane] & 15) in (0, 5, 6) for lane in range(3)) and not d[0] & 0x80:
            blocked.append(row)
    print("    rows %d-%d: %d with no lane open from the ground" % (max(0, top - 60), top, len(blocked)))
    for f in fails[:5]:
        print("    FAIL: " + f)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
