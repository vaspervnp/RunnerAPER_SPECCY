#!/usr/bin/env python3
"""The game as a .Z80 snapshot, for emulators: the moment the tape ends.

    tools/mkz80.py build/loukoumas.bin build/loukoumas.sym build/loading.scr \\
        build/loukoumas.z80 [--model 48|128]

What the tape leaves in memory is all the program needs, so that is what
the snapshot holds: the loading screen at #4000, the code at BIN_ORG (it
starts at LOAD_ADDR), and
the processor about to run its first instruction - interrupts off, IM 1,
the way RANDOMIZE USR hands it over. The program asks nothing of BASIC or
its system variables from there on (tools/zxcheck.py counts the opcodes
fetched from the ROM: none), so they are not reproduced.

The 128K snapshot is the same memory on a 128K - bank 5 at #4000, 2 at
#8000, 0 at #C000, the 48 BASIC ROM paged in - so an emulator gives it the
AY, and the title tune plays on that.

The format is the .Z80 version 3 that every Spectrum emulator reads: the
30-byte header with PC 0, the 54-byte extension, and each 16K page as its
own block, compressed the format's way - ED ED n b for a run of n bytes b,
five or more of them (two for ED itself), and the byte after a lone ED
never the start of a run. Kempston is set as the joystick, which the game
detects for itself in any case.
"""

import argparse
import struct
import sys


def symbols(path):
    sym = {}
    for line in open(path):
        p = line.split()
        if len(p) >= 2 and p[1].startswith("#"):
            sym[p[0].upper()] = int(p[1][1:], 16)
    return sym


def compress(data):
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        b = data[i]
        run = 1
        while i + run < n and data[i + run] == b and run < 255:
            run += 1
        if run >= 5 or (b == 0xED and run >= 2):
            out += bytes((0xED, 0xED, run, b))
            i += run
        else:
            out.append(b)
            i += 1
            if b == 0xED and i < n:            # never the start of a run
                out.append(data[i])
                i += 1
    return bytes(out)


def decompress(data, size):
    out = bytearray()
    i = 0
    while len(out) < size:
        if data[i] == 0xED and data[i + 1] == 0xED:
            out += bytes([data[i + 3]]) * data[i + 2]
            i += 4
        else:
            out.append(data[i])
            i += 1
    return bytes(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("binary")
    ap.add_argument("sym")
    ap.add_argument("screen")
    ap.add_argument("out")
    ap.add_argument("--model", choices=("48", "128"), default="48")
    args = ap.parse_args()
    sym = symbols(args.sym)
    start = sym["LOAD_ADDR"]
    org = sym.get("BIN_ORG", start)             # where the code block goes

    mem = bytearray(0x10000)
    scr = open(args.screen, "rb").read()
    if len(scr) != 6912:
        sys.exit("mkz80: %s is not a SCREEN$" % args.screen)
    mem[0x4000:0x4000 + 6912] = scr
    code = open(args.binary, "rb").read()
    mem[org:org + len(code)] = code

    border = 0
    sp = org - 2                                # where USR's return went
    header = struct.pack(
        "<BBHHHHBBBHHHHBBHHBBB",
        0, 0,                                   # A F
        0, 0,                                   # BC HL
        0,                                      # PC 0: version 2 or 3
        sp,
        0x3F, 0,                                # I R
        border << 1,
        0,                                      # DE
        0, 0, 0,                                # BC' DE' HL'
        0, 0,                                   # A' F'
        0x5C3A, 0,                              # IY as BASIC leaves it, IX
        0, 0,                                   # IFF1 IFF2: interrupts off
        1 | (1 << 6))                           # IM 1, Kempston
    assert len(header) == 30

    hw = 0 if args.model == "48" else 4
    ext = struct.pack("<HBBBBB", start, hw,
                      0x10 if args.model == "128" else 0,     # ROM 1, bank 0
                      0, 0, 0)
    ext += bytes(16)                            # the AY's registers
    ext += bytes(54 - len(ext))                 # T-states, interfaces, keys
    assert len(ext) == 54

    if args.model == "48":
        pages = [(8, 0x4000), (4, 0x8000), (5, 0xC000)]
        banks = {p: mem[a:a + 0x4000] for p, a in pages}
    else:
        banks = {n + 3: bytes(0x4000) for n in range(8)}
        banks[5 + 3] = mem[0x4000:0x8000]
        banks[2 + 3] = mem[0x8000:0xC000]
        banks[0 + 3] = mem[0xC000:0x10000]

    blocks = bytearray()
    for page in sorted(banks):
        data = bytes(banks[page])
        packed = compress(data)
        assert decompress(packed, len(data)) == data
        blocks += struct.pack("<HB", len(packed), page) + packed

    snap = header + struct.pack("<H", len(ext)) + ext + blocks
    open(args.out, "wb").write(snap)
    print("wrote %s, %d bytes: the %sK at #%04X, the loading screen up"
          % (args.out, len(snap), args.model, start))


if __name__ == "__main__":
    main()
