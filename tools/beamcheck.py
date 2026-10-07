#!/usr/bin/env python3
"""Every byte written to the playfield, against the beam (planzx.md 2.2).

    tools/beamcheck.py build/m1.bin build/m1.sym --m1

A game frame copies the whole picture from the ring to the screen and puts
the sprites on it; game frame k is the k-th time the PC reaches `blit`.
Every write to a playfield byte - the bitmap of columns 0-23, and their
attributes, which count as written on all eight lines of their row - is
filed under its game frame and its line. Then, for every frame the ULA
draws and every line of it:

  torn     the ULA fetched the line while a game frame was in the middle of
           writing it (the blit, or a sprite drawn on it later)
  mixed    lines of one frame of the ULA come from different game frames:
           the picture shown is not one picture
  unseen   a game frame whose picture the ULA never showed whole

All three have to be none. --m1 runs the milestone 1 program at the speeds
1 to 8 and also checks what is on the screen after every blit against the
test world worked out here, and reports the time the frames take.
"""

import argparse
import bisect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zxrun import Machine, addr_line  # noqa: E402

PLAY_W = 24


class Beam:
    def __init__(self, m, blit_sym="blit", done_sym="wait_game_frame"):
        self.m = m
        self.gid = -1
        self.writes = {}                # line -> list of [gid, t0, t1]
        self.frames = []                # per game frame: [t_blit, t_last_write, t_done, frame_start]
        m.on_pc(blit_sym, self._blit)
        m.on_pc(done_sym, self._done)
        m.on_screen_write = self._write

    def _blit(self, m):
        self.gid += 1
        self.frames.append([m.t, None, None, (m.t // m.T_FRAME) * m.T_FRAME])

    def _done(self, m):
        if self.frames and self.frames[-1][2] is None:
            self.frames[-1][2] = m.t

    def _mark(self, y, t):
        lst = self.writes.setdefault(y, [])
        if lst and lst[-1][0] == self.gid:
            lst[-1][2] = t
        else:
            lst.append([self.gid, t, t])

    def _write(self, t, a, v):
        if self.gid < 0:
            return
        if a < 0x5800:
            y, x = addr_line(a)
            if x >= PLAY_W:
                return
            self._mark(y, t)
        else:
            r, x = divmod(a - 0x5800, 32)
            if x >= PLAY_W:
                return
            for y in range(r * 8, r * 8 + 8):
                self._mark(y, t)
        if self.frames:
            self.frames[-1][1] = t

    def analyse(self, first_gid, last_gid):
        """Frames of the ULA from game frame first_gid's start to last_gid's."""
        m = self.m
        torn, mixed = [], []
        shown_gids = set()
        f0 = self.frames[first_gid][3] // m.T_FRAME
        f1 = self.frames[last_gid][3] // m.T_FRAME
        starts = {y: [w[1] for w in lst] for y, lst in self.writes.items()}
        for f in range(f0, f1):
            seen = {}
            for y in range(192):
                lst = self.writes.get(y)
                if not lst:
                    continue
                s = f * m.T_FRAME + m.T_PICTURE + y * m.T_LINE
                e = s + 4 * PLAY_W
                i = bisect.bisect_right(starts[y], e) - 1     # last that began by e
                if i < 0:
                    continue
                gid, t0, t1 = lst[i]
                if t1 >= s:
                    torn.append((f, y, gid, t0 - f * m.T_FRAME, t1 - f * m.T_FRAME))
                    continue
                seen.setdefault(gid, []).append(y)
            if len(seen) > 1:
                mixed.append((f, {g: (min(ys), max(ys)) for g, ys in seen.items()}))
            elif len(seen) == 1:
                shown_gids.update(seen)
        unseen = [g for g in range(first_gid, last_gid - 1) if g not in shown_gids]
        return torn, mixed, unseen


def expected_m1(top, j):
    """The test world of src/m1.asm: the playfield bytes and attributes."""
    lines = []
    for y in range(192):
        L = y + j
        row = top - (L >> 3)
        k = L & 7
        if k == 0:
            lines.append(bytes([0xFF] * PLAY_W))
            continue
        e = ((row & 0xFF) * 8 - k + 7) & 0xFF
        lines.append(bytes(0x80 >> ((e + c) & 7) for c in range(PLAY_W)))
    attrs = []
    for cr in range(24):
        row = top - cr - (1 if j > 4 else 0)
        attrs.append((row & 0xFF) % 7 + 1)
    return lines, attrs


def check_m1(args):
    m = Machine(args.binary, args.sym, model=args.model)
    beam = Beam(m)
    bad = 0
    content = {"checked": 0, "wrong": []}

    def after_blit(mm):
        top, j = mm.peekw("cur_top_row"), mm.peek("cur_j")
        lines, attrs = expected_m1(top, j)
        from zxrun import line_addr
        for y in range(192):
            a = line_addr(y)
            if bytes(mm.mem[a:a + PLAY_W]) != lines[y]:
                content["wrong"].append(("line", y, top, j))
                break
        for cr in range(24):
            row = mm.mem[0x5800 + cr * 32:0x5800 + cr * 32 + PLAY_W]
            if any(v != attrs[cr] for v in row):
                content["wrong"].append(("attr", cr, top, j))
                break
        content["checked"] += 1

    m.on_pc("m1_after_blit", after_blit)
    m.run_frames(4)
    print("    speed  game frames  blit starts at T   ends at T   work done at T   missed")
    for speed in range(1, 9):
        m.poke("m1_speed", speed)
        g0 = beam.gid + 2
        missed0 = m.peek("missed_frames")
        m.run_frames(args.frames)
        g1 = beam.gid
        torn, mixed, unseen = beam.analyse(g0, g1)
        fr = beam.frames[g0:g1]
        starts = [b - s for b, _, _, s in fr]
        ends = [w - s for _, w, _, s in fr if w]
        done = [d - s for _, _, d, s in fr if d]
        missed = m.peek("missed_frames") - missed0
        print("    %5d  %11d  %6d - %6d   %6d - %6d   %6d - %6d   %6d"
              % (speed, g1 - g0, min(starts), max(starts), min(ends), max(ends),
                 min(done), max(done), missed))
        for kind, items in (("torn", torn), ("mixed", mixed), ("unseen", unseen)):
            if items:
                bad += 1
                print("      %s: %d, first %r" % (kind, len(items), items[0]))
    print("    %d pictures compared with the test world, %d wrong%s"
          % (content["checked"], len(content["wrong"]),
             (": first %r" % (content["wrong"][0],)) if content["wrong"] else ""))
    if content["wrong"]:
        bad += 1
    print("    sync gave up %d times (a 48K has a floating bus: should be 0)"
          % m.peek("sync_timeouts"))
    if m.peek("sync_timeouts"):
        bad += 1
    return bad


def check_game(args):
    """The game as it plays: --frames TV frames from --from, any pokes."""
    m = Machine(args.binary, args.sym, model=args.model)
    for p in args.poke:
        k, v = p.split("=")
        m.poke(k, int(v, 0))
    beam = Beam(m)
    m.run_frames(args.start)
    g0 = beam.gid + 1
    missed0 = m.peek("missed_frames")
    m.run_frames(args.frames)
    g1 = beam.gid
    torn, mixed, unseen = beam.analyse(g0, g1)
    fr = beam.frames[g0:g1]
    starts = [b - s for b, _, _, s in fr]
    ends = [w - s for _, w, _, s in fr if w]
    done = [d - s for _, _, d, s in fr if d]
    print("    %d game frames: blit from T %d-%d, last write T %d-%d, work done T %d-%d, "
          "%d missed" % (g1 - g0, min(starts), max(starts), min(ends), max(ends),
                         min(done), max(done), m.peek("missed_frames") - missed0))
    bad = 0
    for kind, items in (("torn", torn), ("mixed", mixed), ("unseen", unseen)):
        print("    %-6s %d%s" % (kind, len(items), (", first %r" % (items[0],)) if items else ""))
        bad += len(items)
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("binary")
    ap.add_argument("sym")
    ap.add_argument("--m1", action="store_true", help="the milestone 1 program")
    ap.add_argument("--frames", type=int, default=40, help="TV frames at each speed")
    ap.add_argument("--model", choices=("48", "128"), default="48")
    ap.add_argument("--game", action="store_true", help="the game, as it plays")
    ap.add_argument("--from", dest="start", type=int, default=20, help="first TV frame (--game)")
    ap.add_argument("--poke", action="append", default=[], metavar="SYM=N")
    args = ap.parse_args()
    if args.m1:
        bad = check_m1(args)
    elif args.game:
        bad = check_game(args)
    else:
        sys.exit("beamcheck: nothing to do")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
