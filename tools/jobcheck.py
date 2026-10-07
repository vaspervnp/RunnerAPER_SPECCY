#!/usr/bin/env python3
"""The world's jobs (src/runner.asm world_jobs) timed, against their bounds.

    tools/jobcheck.py build/runner.bin build/runner.sym [--frames N] [--poke SYM=N]

For every job run: its kind, how long it took, and whether it was one the
top row needed there and then (mandatory) or one done ahead. Prints each
kind's longest, against the bound job_bound gave it (last_bound as it
starts); the game frames whose blit started late;
and how far ahead the rows were drawn.
"""

import argparse
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from zxrun import Machine  # noqa: E402

KINDS = ["gen sides", "gen track", "tiles 1", "tiles 2", "slice", "ring_done"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("binary")
    ap.add_argument("sym")
    ap.add_argument("--frames", type=int, default=1000)
    ap.add_argument("--poke", action="append", default=[])
    args = ap.parse_args()
    m = Machine(args.binary, args.sym)
    for p in args.poke:
        name, value = p.split("=")
        m.poke(name, int(value, 0))
    run_job = m.addr("run_job")
    must = m.addr("world_jobs.must") if "WORLD_JOBS.MUST" in m.sym else None
    times = {k: [] for k in range(len(KINDS))}
    bounds = {}
    over = []
    late = []
    ahead = []
    cpu = m.cpu
    blit = m.addr("blit")
    while m.frame < args.frames:
        pc = cpu.pc
        if pc == run_job:
            kind, sp, t0 = cpu.r[7], cpu.sp, cpu.t
            bound = m.peek("last_bound") * 256
            while True:
                m.step()
                if cpu.sp > sp:
                    break
            d = cpu.t - t0
            times[kind].append(d)
            bounds[kind] = max(bounds.get(kind, 0), bound)
            if d > bound:
                over.append((m.frame, KINDS[kind], d, bound))
        elif pc == blit:
            t = cpu.t % m.T_FRAME
            if t > 15000:
                late.append((m.frame, t))
            ahead.append(m.peekw("drawn_row") - m.peekw("cur_top_row"))
            m.step()
        else:
            m.step()
    for k, v in times.items():
        if v:
            q = sorted(v)
            print("    %-10s %5d jobs, median %6d, 90%% %6d, 99%% %6d, max %6d, bounds up to %6d"
                  % (KINDS[k], len(v), statistics.median(v), q[len(q) * 9 // 10],
                     q[len(q) * 99 // 100], max(v), bounds[k]))
    print("    rows drawn ahead at the blit: %s"
          % {a: ahead.count(a) for a in sorted(set(ahead))})
    print("    blits late: %d%s" % (len(late), (", first " + str(late[:5])) if late else ""))
    print("    jobs over their bound: %d%s" % (len(over), (", " + str(over[:5])) if over else ""))
    sys.exit(1 if late or over else 0)


if __name__ == "__main__":
    main()
