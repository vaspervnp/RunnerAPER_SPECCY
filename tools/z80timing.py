#!/usr/bin/env python3
"""Every instruction z80check.py times, against the data sheet.

    tools/z80timing.py

z80check builds an instruction's cost out of its memory cycles and its
internal ones, because that is the only way contention can land in the right
place. This runs each instruction once, in uncontended RAM, and checks the
total is the number Zilog prints - so a cycle charged twice, or one forgotten,
cannot hide behind the contention model.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import z80check as z  # noqa: E402

# (bytes, T, how to set up) - the setup makes conditional ones go the way
# the line says. Taken branches are listed separately.
CASES = [
    ("00", 4, "nop"), ("41", 4, "ld b,c"), ("3E 05", 7, "ld a,n"),
    ("7E", 7, "ld a,(hl)"), ("77", 7, "ld (hl),a"), ("36 05", 10, "ld (hl),n"),
    ("0A", 7, "ld a,(bc)"), ("12", 7, "ld (de),a"),
    ("3A 00 C0", 13, "ld a,(nn)"), ("32 00 C0", 13, "ld (nn),a"),
    ("2A 00 C0", 16, "ld hl,(nn)"), ("22 00 C0", 16, "ld (nn),hl"),
    ("21 00 C0", 10, "ld hl,nn"), ("F9", 6, "ld sp,hl"),
    ("23", 6, "inc hl"), ("0B", 6, "dec bc"), ("09", 11, "add hl,bc"),
    ("04", 4, "inc b"), ("34", 11, "inc (hl)"), ("35", 11, "dec (hl)"),
    ("86", 7, "add a,(hl)"), ("C6 01", 7, "add a,n"), ("A0", 4, "and b"),
    ("07", 4, "rlca"), ("27", 4, "daa"), ("2F", 4, "cpl"), ("37", 4, "scf"),
    ("C5", 11, "push bc"), ("E1", 10, "pop hl"), ("E3", 19, "ex (sp),hl"),
    ("EB", 4, "ex de,hl"), ("D9", 4, "exx"), ("08", 4, "ex af,af'"),
    ("C3 00 90", 10, "jp nn"), ("E9", 4, "jp (hl)"),
    ("C2 00 90", 10, "jp nz,nn (Z set: not taken)", "zf"),
    ("18 00", 12, "jr e"),
    ("20 00", 7, "jr nz,e (Z set: not taken)", "zf"),
    ("20 00", 12, "jr nz,e (taken)"),
    ("10 00", 13, "djnz (taken)"), ("10 00", 8, "djnz (B=1: not taken)", "b1"),
    ("CD 00 90", 17, "call nn"),
    ("C4 00 90", 10, "call nz,nn (Z set: not taken)", "zf"),
    ("C4 00 90", 17, "call nz,nn (taken)"),
    ("C9", 10, "ret"), ("C0", 11, "ret nz (taken)"),
    ("C0", 5, "ret nz (Z set: not taken)", "zf"),
    ("FF", 11, "rst 38"),
    ("D3 FE", 11, "out (n),a"), ("DB FE", 11, "in a,(n)"),
    ("F3", 4, "di"), ("FB", 4, "ei"),
    ("CB 27", 8, "sla a"), ("CB 46", 12, "bit 0,(hl)"), ("CB C6", 15, "set 0,(hl)"),
    ("CB 16", 15, "rl (hl)"),
    ("ED 78", 12, "in a,(c)"), ("ED 79", 12, "out (c),a"),
    ("ED 42", 15, "sbc hl,bc"), ("ED 4A", 15, "adc hl,bc"),
    ("ED 43 00 C0", 20, "ld (nn),bc"), ("ED 4B 00 C0", 20, "ld bc,(nn)"),
    ("ED 44", 8, "neg"), ("ED 47", 9, "ld i,a"), ("ED 57", 9, "ld a,i"),
    ("ED 5E", 8, "im 2"), ("ED 4D", 14, "reti"),
    ("ED A0", 16, "ldi"), ("ED B0", 16, "ldir (BC=1: last)", "bc1"),
    ("ED B0", 21 + 16, "ldir (BC=2: one repeat, then last)", "bc2"),
    ("ED A1", 16, "cpi"),
    ("DD 21 00 C0", 14, "ld ix,nn"), ("DD 23", 10, "inc ix"),
    ("DD 09", 15, "add ix,bc"), ("DD E5", 15, "push ix"), ("DD E1", 14, "pop ix"),
    ("DD F9", 10, "ld sp,ix"), ("DD E9", 8, "jp (ix)"),
    ("DD 7E 01", 19, "ld a,(ix+d)"), ("DD 77 01", 19, "ld (ix+d),a"),
    ("DD 36 01 05", 19, "ld (ix+d),n"), ("DD 86 01", 19, "add a,(ix+d)"),
    ("DD 34 01", 23, "inc (ix+d)"), ("DD 35 01", 23, "dec (ix+d)"),
    ("DD CB 01 46", 20, "bit 0,(ix+d)"), ("DD CB 01 C6", 23, "set 0,(ix+d)"),
    ("DD 2A 00 C0", 20, "ld ix,(nn)"), ("DD 22 00 C0", 20, "ld (nn),ix"),
    ("DD 26 05", 11, "ld ixh,n"), ("DD 7C", 8, "ld a,ixh"),
    ("FD 7E 01", 19, "ld a,(iy+d)"),
]


def run(code, setup):
    mem = bytearray(0x10000)
    org = 0x8000
    b = bytes.fromhex(code)
    mem[org:org + len(b)] = b
    cpu = z.Z80(mem, z.ZXIO())
    cpu.pc = org
    cpu.sp = 0xF000
    cpu.hl = cpu.de = 0xC000
    cpu.ix = cpu.iy = 0xC000
    cpu.bc = 0x0202
    cpu.i = 0xFD
    if setup == "zf":
        cpu.zf = True
    elif setup == "b1":
        cpu.bc = 0x0102
    elif setup == "bc1":
        cpu.bc = 1
    elif setup == "bc2":
        cpu.bc = 2
    cpu.t = 0
    cpu.step()
    while cpu.pc == org:                        # a repeating instruction
        cpu.step()
    return cpu.t


def main():
    bad = 0
    for case in CASES:
        code, want, name = case[:3]
        setup = case[3] if len(case) > 3 else None
        got = run(code, setup)
        if got != want:
            bad += 1
            print("    %-36s %2d T, the data sheet says %d" % (name, got, want))
    print("    %d instructions timed, %d wrong" % (len(CASES), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
