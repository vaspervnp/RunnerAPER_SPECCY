#!/usr/bin/env python3
"""Where a game frame's time goes: T-states by routine (the nearest symbol
at or below the PC), and the frames' loads.

    tools/zxprofile.py build/runner.bin build/runner.sym [--frames N] [--from N]
"""
import argparse
import bisect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zxrun import Machine  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("binary")
    ap.add_argument("sym")
    ap.add_argument("--frames", type=int, default=400)
    ap.add_argument("--from", dest="start", type=int, default=50)
    ap.add_argument("--poke", action="append", default=[], metavar="SYM=N")
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()
    m = Machine(args.binary, args.sym)
    for p in args.poke:
        k, v = p.split("=")
        m.poke(k, int(v, 0))
    names = {}
    for k, v in sorted(m.sym.items(), key=lambda kv: kv[0]):
        if "." not in k and v >= 0x6000:
            names.setdefault(v, k)
    addrs = sorted(names)
    prof = {}
    loads = []
    st = {"start": None}

    def frame_start(mm):
        st["start"] = mm.t

    def frame_end(mm):
        if st["start"] is not None:
            loads.append(mm.t - st["start"])

    m.on_pc("beam_sync", frame_start)
    m.on_pc("wait_game_frame", frame_end)
    m.run_frames(args.start)
    end = (m.frame + args.frames) * m.T_FRAME
    cpu = m.cpu
    del loads[:]
    while cpu.t < end:
        pc, t0 = cpu.pc, cpu.t
        m.step()
        i = bisect.bisect_right(addrs, pc) - 1
        if i >= 0 and not cpu.halted:
            n = names[addrs[i]]
            prof[n] = prof.get(n, 0) + cpu.t - t0
    total = sum(prof.values())
    games = max(1, len(loads))
    print("T-states a game frame by routine (%d game frames):" % games)
    for n, t in sorted(prof.items(), key=lambda kv: -kv[1])[:args.top]:
        print("  %-24s %7d  %5.1f%%" % (n, t // games, 100.0 * t / total))
    if loads:
        loads.sort()
        print("work from beam_sync to wait_game_frame: median %d, 90%% %d, max %d (frame %d)"
              % (loads[len(loads) // 2], loads[len(loads) * 9 // 10], loads[-1], 2 * m.T_FRAME))
    print("missed frames:", m.peek("missed_frames"))


if __name__ == "__main__":
    main()
