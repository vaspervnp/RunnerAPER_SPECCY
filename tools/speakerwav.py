#!/usr/bin/env python3
"""The beeper, as something to listen to.

    tools/speakerwav.py LOG OUT.wav [--from FRAME] [--model 48|128]

LOG is what tools/z80check.py --speaker writes: the T-state of every flip
of the speaker bit. Between two flips the speaker is either in or out, so
the sound is a square wave with its edges exactly where the program put
them; each sample of the WAV is how much of its 1/44100 s the speaker spent
out, which is all the low-pass a real speaker and its case provide.
"""

import argparse
import os
import struct
import sys
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from z80check import MODELS  # noqa: E402

RATE = 44100
CPU_HZ = {"48": 3500000, "128": 3546900}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log")
    ap.add_argument("out")
    ap.add_argument("--from", dest="start", type=int, default=0, metavar="FRAME")
    ap.add_argument("--model", choices=sorted(MODELS), default="48")
    args = ap.parse_args()
    t_line, lines = MODELS[args.model][:2]
    t0 = args.start * t_line * lines
    flips = [int(l.split()[0]) for l in open(args.log)]
    level = sum(1 for t in flips if t < t0) & 1
    flips = [t - t0 for t in flips if t >= t0]
    if not flips:
        sys.exit("speakerwav: no sound after frame %d" % args.start)
    per = CPU_HZ[args.model] / RATE                 # T-states a sample
    end = flips[-1] + int(per)
    samples = bytearray()
    i, t = 0, 0.0
    while t < end:
        t1 = t + per
        on, a = 0.0, t
        while i < len(flips) and flips[i] < t1:
            if level:
                on += flips[i] - a
            a = flips[i]
            level ^= 1
            i += 1
        if level:
            on += t1 - a
        samples += struct.pack("<h", int((on / per - 0.5) * 2 * 12000))
        t = t1
    with wave.open(args.out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(samples))
    print("speakerwav: %s, %.1f seconds" % (args.out, len(samples) / 2 / RATE))


if __name__ == "__main__":
    main()
