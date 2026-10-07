#!/usr/bin/env python3
"""Run an assembled Spectrum program on a small Z80 interpreter that keeps a
48K's time, then render what the ULA would show.

    make build/loukoumas.bin
    tools/z80check.py build/loukoumas.bin --org 0x8000 --png /tmp/screen.png

The clock is T-states, 69888 to the frame, and the interrupt arrives at T = 0
of every frame and stays up for 32 T. An instruction costs what the data sheet
says, built up the way the chip spends it: 4 T for each opcode fetch, 3 for
each other memory access, 4 for an I/O cycle, and the internal cycles on top
(T_INT and the prefix handlers). That is what lets --beam say where the beam
is when a sprite is drawn: line y of the picture is fetched from
T = 14336 + 224y.

Contention is modelled the way Fuse documents it for the 48K. While the ULA
is fetching the picture - 128 of each line's 224 T, for 192 lines from
T = 14335 - any access to #4000-#7FFF waits 6,5,4,3,2,1,0,0 T depending on
where in the ULA's eight-T cycle it lands, and I/O follows its own pattern by
port. Outside those 128 T, and anywhere else in memory, nothing waits.

What it does NOT model, and so cannot tell you:

  * Internal cycles are placed and contended as Fuse's timing tables have
    them for the instructions the game uses: the five T of a taken JR at
    pc+1, the one of INC (HL) at HL, the repeat of LDIR at DE, the five of
    (IX+d) at the displacement. The rest go where the instruction ends, and
    the ones with IR on the bus are only contended if I is in #40-#7F.
  * The floating bus beyond its outline: an unused port reads the byte the
    ULA is fetching - bitmap, attribute, bitmap, attribute, then four T of
    nothing - while it draws, and #FF otherwise. Good enough to show that
    a program listening for a joystick that is not there hears garbage.
  * The +2A/+3. --model 128 is the 128K and +2: 228 T a line, 311 lines,
    70908 T a frame, the picture from T 14362, the same contention pattern
    on #4000-#7FFF (bank 5), nothing paged in at #C000 that waits.

It aborts on any opcode it does not implement rather than guessing, so a clean
run means the code really did execute.
"""

import argparse
import bisect
import os
import sys

PARITY = [bin(i).count("1") % 2 == 0 for i in range(256)]

# The 48K's frame.
T_PER_LINE = 224
FRAME_LINES = 312
T_FRAME = T_PER_LINE * FRAME_LINES          # 69888
T_PICTURE = 14336                           # INT to the first line of the picture
T_CONTEND = 14335                           # first contended T-state
INT_LENGTH = 32
CONTEND_PATTERN = (6, 5, 4, 3, 2, 1, 0, 0)

#: --model: T a line, lines, first contended T, the picture's first T, INT.
MODELS = {"48": (224, 312, 14335, 14336, 32),
          "128": (228, 311, 14361, 14362, 36)}


def set_model(name):
    """Make the module's frame the given model's, for everything after."""
    global T_PER_LINE, FRAME_LINES, T_FRAME, T_CONTEND, T_PICTURE, INT_LENGTH
    T_PER_LINE, FRAME_LINES, T_CONTEND, T_PICTURE, INT_LENGTH = MODELS[name]
    T_FRAME = T_PER_LINE * FRAME_LINES


def contention(t):
    """How long an access to contended RAM starting at T-state t waits."""
    tf = t % T_FRAME - T_CONTEND
    if tf < 0 or tf >= 192 * T_PER_LINE:
        return 0
    pos = tf % T_PER_LINE
    if pos >= 128:
        return 0
    return CONTEND_PATTERN[pos & 7]


#: T-states an unprefixed instruction spends beyond its memory and I/O cycles
#: with IR on the address bus, straight after the opcode fetch. The ones with
#: a memory address on the bus are charged where they happen, by Z80.idle:
#: JR +5 taken, DJNZ +1 and +5 more taken, CALL +1, INC (HL) +1, EX (SP),HL +3.
T_INT = [0] * 256
for _op in (0x03, 0x13, 0x23, 0x33, 0x0B, 0x1B, 0x2B, 0x3B):
    T_INT[_op] = 2                          # INC/DEC rr: 6 T
for _op in (0x09, 0x19, 0x29, 0x39):
    T_INT[_op] = 7                          # ADD HL,rr: 11 T
for _op in (0xC5, 0xD5, 0xE5, 0xF5):
    T_INT[_op] = 1                          # PUSH: 11 T
for _op in range(0xC7, 0x100, 8):
    T_INT[_op] = 1                          # RST: 11 T
for _op in (0xC0, 0xC8, 0xD0, 0xD8, 0xE0, 0xE8, 0xF0, 0xF8):
    T_INT[_op] = 1                          # RET cc: 5 T, or 11 taken
T_INT[0xF9] = 2                             # LD SP,HL: 6 T


#: An LDIR longer than this is reported: almost always a length that reached
#: zero, was decremented once more and became 65536.
LDIR_SUSPECT = 20000


class Unsupported(Exception):
    pass


# ---------------------------------------------------------------------------
# CPU
# ---------------------------------------------------------------------------

class Z80:
    """Registers are indexed the way the opcodes encode them: B C D E H L (HL) A."""

    B, C, D, E, H, L, MHL, A = range(8)

    def __init__(self, mem, io):
        self.m = mem
        self.io = io
        self.r = [0] * 8
        self.r2 = [0] * 8                      # shadow set for EXX
        self.ix = self.iy = 0
        self.sp = 0
        self.pc = 0
        self.sf = self.zf = self.hf = self.pf = self.nf = self.cf = False
        self.af2 = 0
        self.iff = False
        self.imode = 0
        self.halted = False
        self.ei_pending = False                # EI holds interrupts off one more instruction
        self.i = 0
        self.t = 0                             # T-states since the run began
        self.waited = 0                        # of which, contention
        self.rom_top = 0                       # writes below this are ignored

    # -- memory / fetch -----------------------------------------------------
    trap = None
    trap_value = None
    trap_frame = None
    trap_hit = None
    big_ldir = None

    def _access(self, a, t):
        if 0x4000 <= a < 0x8000:
            w = contention(self.t)
            self.t += w
            self.waited += w
        self.t += t

    def idle(self, a, n):
        """n internal T-states with address a on the bus: each one waits if
        a is contended, the same as the first T of an access would."""
        a &= 0xFFFF
        if 0x4000 <= a < 0x8000:
            for _ in range(n):
                w = contention(self.t)
                self.t += w + 1
                self.waited += w
        else:
            self.t += n

    def idle_ir(self, n):
        if n:
            self.idle(self.i << 8, n)

    def rb(self, a):
        a &= 0xFFFF
        self._access(a, 3)
        return self.m[a]

    def wb(self, a, v):
        a &= 0xFFFF
        self._access(a, 3)
        if a < self.rom_top:
            return
        if (a == self.trap and self.trap_hit is None
                and (self.trap_value is None or (v & 0xFF) == self.trap_value)
                and (self.trap_frame is None or self.io.frame() >= self.trap_frame)):
            self.trap_hit = (self.pc, v, self.io.frame(),
                             self.hl, self.de, self.bc, self.sp,
                             self.rb(self.sp) | (self.rb(self.sp + 1) << 8))
        self.m[a] = v & 0xFF

    def rw(self, a):
        return self.rb(a) | (self.rb(a + 1) << 8)

    def ww(self, a, v):
        self.wb(a, v)
        self.wb(a + 1, v >> 8)

    def fetch(self):
        v = self.rb(self.pc)
        self.pc = (self.pc + 1) & 0xFFFF
        return v

    def fetch_op(self):
        """An M1 cycle: an opcode fetch, 4 T rather than 3."""
        self._access(self.pc, 4)
        v = self.m[self.pc]
        self.pc = (self.pc + 1) & 0xFFFF
        return v

    def io_cycle(self, port):
        """An I/O cycle and its contention on a 48K: a port whose high byte
        points into #4000-#7FFF is contended as if it were memory, and so is
        every even port, because the ULA answers those."""
        hi = 0x40 <= (port >> 8) < 0x80
        ula = not port & 1
        if not hi and not ula:
            self.t += 4
            return
        if not hi:                              # N:1, C:3
            self.t += 1
            w = contention(self.t)
            self.t += w + 3
            self.waited += w
            return
        for n in ((1, 3) if ula else (1, 1, 1, 1)):
            w = contention(self.t)
            self.t += w + n
            self.waited += w

    def fetchw(self):
        v = self.rw(self.pc)
        self.pc = (self.pc + 2) & 0xFFFF
        return v

    def fetchd(self):
        d = self.fetch()
        return d - 256 if d > 127 else d

    # -- register pairs -----------------------------------------------------
    def _pair(self, hi):
        return (self.r[hi] << 8) | self.r[hi + 1]

    def _setpair(self, hi, v):
        self.r[hi] = (v >> 8) & 0xFF
        self.r[hi + 1] = v & 0xFF

    bc = property(lambda s: s._pair(0), lambda s, v: s._setpair(0, v))
    de = property(lambda s: s._pair(2), lambda s, v: s._setpair(2, v))
    hl = property(lambda s: s._pair(4), lambda s, v: s._setpair(4, v))

    def rr(self, i):                           # BC DE HL SP
        return (self.bc, self.de, self.hl, self.sp)[i]

    def set_rr(self, i, v):
        if i == 0:
            self.bc = v
        elif i == 1:
            self.de = v
        elif i == 2:
            self.hl = v
        else:
            self.sp = v & 0xFFFF

    # -- 8-bit operand, where 6 means (HL) ----------------------------------
    def g8(self, i):
        return self.rb(self.hl) if i == 6 else self.r[i]

    def s8(self, i, v):
        if i == 6:
            self.wb(self.hl, v)
        else:
            self.r[i] = v & 0xFF

    # -- flags --------------------------------------------------------------
    # Bits 3 and 5 of F are kept as POP AF left them, so that POP AF / PUSH
    # AF carry any byte through unchanged, as the chip does (a stack copy
    # through AF depends on it). What the ALU leaves in them is not modelled.
    f35 = 0

    def get_f(self):
        return (self.f35 | (0x80 if self.sf else 0) | (0x40 if self.zf else 0) |
                (0x10 if self.hf else 0) | (0x04 if self.pf else 0) |
                (0x02 if self.nf else 0) | (0x01 if self.cf else 0))

    def set_f(self, f):
        self.f35 = f & 0x28
        self.sf = bool(f & 0x80)
        self.zf = bool(f & 0x40)
        self.hf = bool(f & 0x10)
        self.pf = bool(f & 0x04)
        self.nf = bool(f & 0x02)
        self.cf = bool(f & 0x01)

    def _sz(self, v):
        self.zf = v == 0
        self.sf = bool(v & 0x80)

    # -- ALU ----------------------------------------------------------------
    def add8(self, v, carry=0):
        a = self.r[7]
        t = a + v + carry
        res = t & 0xFF
        self.hf = ((a & 0xF) + (v & 0xF) + carry) > 0xF
        self.cf = t > 0xFF
        self.pf = bool((~(a ^ v)) & (a ^ res) & 0x80)
        self.nf = False
        self._sz(res)
        self.r[7] = res

    def sub8(self, v, carry=0, store=True):
        a = self.r[7]
        t = a - v - carry
        res = t & 0xFF
        self.hf = ((a & 0xF) - (v & 0xF) - carry) < 0
        self.cf = t < 0
        self.pf = bool((a ^ v) & (a ^ res) & 0x80)
        self.nf = True
        self._sz(res)
        if store:
            self.r[7] = res

    def logic8(self, v, op):
        a = self.r[7]
        res = {0: a & v, 1: a ^ v, 2: a | v}[op]
        self.r[7] = res
        self.hf = op == 0
        self.cf = self.nf = False
        self.pf = PARITY[res]
        self._sz(res)

    def inc8(self, v):
        res = (v + 1) & 0xFF
        self.hf = (v & 0xF) == 0xF
        self.pf = v == 0x7F
        self.nf = False
        self._sz(res)
        return res

    def dec8(self, v):
        res = (v - 1) & 0xFF
        self.hf = (v & 0xF) == 0
        self.pf = v == 0x80
        self.nf = True
        self._sz(res)
        return res

    def add16(self, a, b):
        t = a + b
        self.hf = ((a & 0xFFF) + (b & 0xFFF)) > 0xFFF
        self.cf = t > 0xFFFF
        self.nf = False
        return t & 0xFFFF

    def adc16(self, a, b):
        c = 1 if self.cf else 0
        t = a + b + c
        res = t & 0xFFFF
        self.hf = ((a & 0xFFF) + (b & 0xFFF) + c) > 0xFFF
        self.cf = t > 0xFFFF
        self.pf = bool((~(a ^ b)) & (a ^ res) & 0x8000)
        self.nf = False
        self.zf = res == 0
        self.sf = bool(res & 0x8000)
        return res

    def sbc16(self, a, b):
        c = 1 if self.cf else 0
        t = a - b - c
        res = t & 0xFFFF
        self.hf = ((a & 0xFFF) - (b & 0xFFF) - c) < 0
        self.cf = t < 0
        self.pf = bool((a ^ b) & (a ^ res) & 0x8000)
        self.nf = True
        self.zf = res == 0
        self.sf = bool(res & 0x8000)
        return res

    # -- stack / flow -------------------------------------------------------
    sp_floor = None
    sp_hit = None

    def push(self, v):
        self.sp = (self.sp - 2) & 0xFFFF
        if (self.sp_floor is not None and self.sp < self.sp_floor
                and self.sp_hit is None):
            self.sp_hit = (self.pc, self.sp, self.io.frame())
        self.ww(self.sp, v)

    def pop(self):
        v = self.rw(self.sp)
        self.sp = (self.sp + 2) & 0xFFFF
        return v

    def cond(self, i):
        return (not self.zf, self.zf, not self.cf, self.cf,
                not self.pf, self.pf, not self.sf, self.sf)[i]

    # -- rotates / shifts ---------------------------------------------------
    def rot(self, op, v):
        if op == 0:                                     # rlc
            self.cf = bool(v & 0x80)
            v = ((v << 1) | (1 if self.cf else 0)) & 0xFF
        elif op == 1:                                   # rrc
            self.cf = bool(v & 1)
            v = ((v >> 1) | (0x80 if self.cf else 0)) & 0xFF
        elif op == 2:                                   # rl
            c = self.cf
            self.cf = bool(v & 0x80)
            v = ((v << 1) | (1 if c else 0)) & 0xFF
        elif op == 3:                                   # rr
            c = self.cf
            self.cf = bool(v & 1)
            v = ((v >> 1) | (0x80 if c else 0)) & 0xFF
        elif op == 4:                                   # sla
            self.cf = bool(v & 0x80)
            v = (v << 1) & 0xFF
        elif op == 5:                                   # sra
            self.cf = bool(v & 1)
            v = ((v >> 1) | (v & 0x80)) & 0xFF
        elif op == 6:                                   # sll (undocumented)
            self.cf = bool(v & 0x80)
            v = ((v << 1) | 1) & 0xFF
        else:                                           # srl
            self.cf = bool(v & 1)
            v = (v >> 1) & 0xFF
        self.hf = self.nf = False
        self.pf = PARITY[v]
        self._sz(v)
        return v

    # -- one instruction ----------------------------------------------------
    def step(self):
        op = self.fetch_op()
        self.idle_ir(T_INT[op])

        if op == 0xCB:
            return self.op_cb()
        if op == 0xED:
            return self.op_ed()
        if op in (0xDD, 0xFD):
            return self.op_index(op)

        hi, lo = op >> 6, op & 7
        mid = (op >> 3) & 7

        if op == 0x00:
            return
        if op == 0x76:
            self.halted = True
            return
        if hi == 1:                                     # ld r,r'
            return self.s8(mid, self.g8(lo))
        if hi == 2:                                     # alu a,r
            return self.alu(mid, self.g8(lo))
        if hi == 0:
            if lo == 0:
                if op == 0x08:
                    af = (self.r[7] << 8) | self.get_f()
                    self.r[7] = self.af2 >> 8
                    self.set_f(self.af2 & 0xFF)
                    self.af2 = af
                elif op == 0x10:                        # djnz: 8 T, 13 taken
                    self.idle_ir(1)
                    d = self.fetchd()
                    self.r[0] = (self.r[0] - 1) & 0xFF
                    if self.r[0]:
                        self.idle(self.pc - 1, 5)
                        self.pc = (self.pc + d) & 0xFFFF
                elif op == 0x18:                        # jr: 12 T
                    d = self.fetchd()
                    self.idle(self.pc - 1, 5)
                    self.pc = (self.pc + d) & 0xFFFF
                else:                                   # jr cc,e: 7 T, 12 taken
                    d = self.fetchd()
                    if self.cond(mid - 4):
                        self.idle(self.pc - 1, 5)
                        self.pc = (self.pc + d) & 0xFFFF
                return
            if lo == 1:
                if op & 8:
                    self.hl = self.add16(self.hl, self.rr(mid >> 1))
                else:
                    self.set_rr(mid >> 1, self.fetchw())
                return
            if lo == 2:
                if op == 0x02: self.wb(self.bc, self.r[7])
                elif op == 0x0A: self.r[7] = self.rb(self.bc)
                elif op == 0x12: self.wb(self.de, self.r[7])
                elif op == 0x1A: self.r[7] = self.rb(self.de)
                elif op == 0x22: self.ww(self.fetchw(), self.hl)
                elif op == 0x2A: self.hl = self.rw(self.fetchw())
                elif op == 0x32: self.wb(self.fetchw(), self.r[7])
                else: self.r[7] = self.rb(self.fetchw())
                return
            if lo == 3:
                i = mid >> 1
                self.set_rr(i, (self.rr(i) + (-1 if op & 8 else 1)) & 0xFFFF)
                return
            if lo in (4, 5):
                v = self.g8(mid)
                if mid == 6:
                    self.idle(self.hl, 1)               # inc/dec (hl): 11 T
                return self.s8(mid, self.inc8(v) if lo == 4 else self.dec8(v))
            if lo == 6:
                return self.s8(mid, self.fetch())
            # lo == 7: the accumulator/flag oddities
            if op in (0x07, 0x0F, 0x17, 0x1F):
                self.r[7] = self.rot(op >> 3, self.r[7])
                self.zf = self.sf = False               # these four leave S/Z alone
                self.pf = False
                return
            if op == 0x27:
                return self.daa()
            if op == 0x2F:
                self.r[7] ^= 0xFF
                self.hf = self.nf = True
                return
            if op == 0x37:
                self.cf = True
                self.hf = self.nf = False
                return
            if op == 0x3F:
                self.hf = self.cf
                self.cf = not self.cf
                self.nf = False
                return

        # hi == 3
        if lo == 0:
            if self.cond(mid):
                self.pc = self.pop()
            return
        if lo == 1:
            if op & 8:
                if op == 0xC9: self.pc = self.pop()
                elif op == 0xD9:
                    # EXX is BC DE HL and nothing else - A has its own
                    # ex af,af' - so only the first six of r may move.
                    self.r[:6], self.r2[:6] = self.r2[:6], self.r[:6]
                elif op == 0xE9: self.pc = self.hl
                else: self.sp = self.hl
            else:
                v = self.pop()
                i = mid >> 1
                if i == 3:
                    self.r[7] = v >> 8
                    self.set_f(v & 0xFF)
                else:
                    self.set_rr(i, v)
            return
        if lo == 2:
            t = self.fetchw()
            if self.cond(mid):
                self.pc = t
            return
        if lo == 3:
            if op == 0xC3: self.pc = self.fetchw()
            elif op == 0xD3:
                port = (self.r[7] << 8) | self.fetch()
                self.io_cycle(port)
                self.io.out(port, self.r[7])
            elif op == 0xDB:
                port = (self.r[7] << 8) | self.fetch()
                self.io_cycle(port)
                self.r[7] = self.io.inp(port)
            elif op == 0xE3:                            # ex (sp),hl: 19 T
                t = self.rw(self.sp)
                self.idle(self.sp + 1, 1)
                self.ww(self.sp, self.hl)
                self.idle(self.sp, 2)
                self.hl = t
            elif op == 0xEB:
                t = self.de
                self.de = self.hl
                self.hl = t
            elif op == 0xF3: self.iff = False
            elif op == 0xFB:
                self.iff = True
                self.ei_pending = True
            return
        if lo == 4:                                     # call cc: 10 T, 17 taken
            t = self.fetchw()
            if self.cond(mid):
                self.idle(self.pc - 1, 1)
                self.push(self.pc)
                self.pc = t
            return
        if lo == 5:
            if op & 8:
                if op == 0xCD:                          # call: 17 T
                    t = self.fetchw()
                    self.idle(self.pc - 1, 1)
                    self.push(self.pc)
                    self.pc = t
                    return
                raise Unsupported("opcode #%02X at #%04X" % (op, self.pc - 1))
            i = mid >> 1
            self.push((self.r[7] << 8) | self.get_f() if i == 3 else self.rr(i))
            return
        if lo == 6:
            return self.alu(mid, self.fetch())
        # lo == 7: rst
        self.push(self.pc)
        self.pc = mid * 8

    def alu(self, op, v):
        if op == 0: self.add8(v)
        elif op == 1: self.add8(v, 1 if self.cf else 0)
        elif op == 2: self.sub8(v)
        elif op == 3: self.sub8(v, 1 if self.cf else 0)
        elif op == 4: self.logic8(v, 0)
        elif op == 5: self.logic8(v, 1)
        elif op == 6: self.logic8(v, 2)
        else: self.sub8(v, 0, store=False)

    def daa(self):
        a = self.r[7]
        t = 0
        if self.hf or (a & 0xF) > 9:
            t |= 6
        if self.cf or a > 0x99:
            t |= 0x60
            self.cf = True
        if self.nf:
            self.hf = self.hf and (a & 0xF) < 6
            a = (a - t) & 0xFF
        else:
            self.hf = (a & 0xF) > 9
            a = (a + t) & 0xFF
        self.r[7] = a
        self.pf = PARITY[a]
        self._sz(a)

    # -- CB prefix ----------------------------------------------------------
    def op_cb(self):
        op = self.fetch_op()
        hi, reg, bit = op >> 6, op & 7, (op >> 3) & 7
        v = self.g8(reg)
        if reg == 6:
            self.idle(self.hl, 1)               # (HL): 12 T for BIT, 15 for the rest
        if hi == 0:
            return self.s8(reg, self.rot(bit, v))
        if hi == 1:                                     # bit
            self.zf = not (v & (1 << bit))
            self.pf = self.zf
            self.sf = bit == 7 and not self.zf
            self.hf = True
            self.nf = False
            return
        if hi == 2:
            return self.s8(reg, v & ~(1 << bit))
        return self.s8(reg, v | (1 << bit))

    # -- ED prefix ----------------------------------------------------------
    def op_ed(self):
        op = self.fetch_op()
        mid = (op >> 3) & 7
        if op & 0xC7 == 0x40:                           # in r,(c)
            self.io_cycle(self.bc)
            v = self.io.inp(self.bc)
            if mid != 6:
                self.r[mid] = v
            self.hf = self.nf = False
            self.pf = PARITY[v]
            self._sz(v)
            return
        if op & 0xC7 == 0x41:                           # out (c),r
            self.io_cycle(self.bc)
            return self.io.out(self.bc, 0 if mid == 6 else self.r[mid])
        if op & 0xC7 == 0x42:
            self.idle_ir(7)                             # adc/sbc hl,rr: 15 T
        if op & 0xCF == 0x42:                           # sbc hl,rr
            return setattr(self, "hl", self.sbc16(self.hl, self.rr(mid >> 1)))
        if op & 0xCF == 0x4A:                           # adc hl,rr
            return setattr(self, "hl", self.adc16(self.hl, self.rr(mid >> 1)))
        if op & 0xCF == 0x43:                           # ld (nn),rr
            return self.ww(self.fetchw(), self.rr(mid >> 1))
        if op & 0xCF == 0x4B:                           # ld rr,(nn)
            return self.set_rr(mid >> 1, self.rw(self.fetchw()))
        if op & 0xC7 == 0x44:                           # neg
            a = self.r[7]
            self.r[7] = 0
            self.sub8(a)
            return
        if op & 0xC7 == 0x45:                           # retn / reti
            self.pc = self.pop()
            return
        if op & 0xC7 == 0x46:                           # im n
            self.imode = (0, 0, 1, 2)[mid & 3]
            return
        if op in (0x47, 0x4F, 0x57, 0x5F):              # ld i/r,a and back: 9 T
            self.idle_ir(1)
            if op == 0x47:
                self.i = self.r[7]
            elif op == 0x57:
                self.r[7] = self.i
                self._sz(self.i)
                self.pf = self.iff
                self.hf = self.nf = False
            return
        if op in (0xA0, 0xA8, 0xB0, 0xB8):              # ldi ldd ldir lddr
            step = 1 if op in (0xA0, 0xB0) else -1
            repeat = op >= 0xB0
            if repeat and self.bc > LDIR_SUSPECT and self.big_ldir is None:
                # Almost always a zero length that wrapped to 65535, which on
                # a CPC smears one byte over the whole of memory.
                self.big_ldir = (self.pc - 2, self.bc, self.hl, self.de,
                                 self.rb(self.sp) | (self.rb(self.sp + 1) << 8))
            # One byte a step, and a repeat is the instruction run again from
            # its own fetch, the way the Z80 does it: 21 T and then 16 for
            # the last, and an interrupt can land between any two of them.
            self.wb(self.de, self.rb(self.hl))
            self.idle(self.de, 2)
            self.hl = (self.hl + step) & 0xFFFF
            self.de = (self.de + step) & 0xFFFF
            self.bc = (self.bc - 1) & 0xFFFF
            if repeat and self.bc:
                self.idle(self.de - step, 5)
                self.pc = (self.pc - 2) & 0xFFFF
            self.hf = self.nf = False
            self.pf = self.bc != 0
            return
        if op in (0xA1, 0xA9, 0xB1, 0xB9):              # cpi cpd cpir cpdr
            step = 1 if op in (0xA1, 0xB1) else -1
            repeat = op >= 0xB0
            v = self.rb(self.hl)                        # 16 T, 21 for a repeat
            self.idle(self.hl, 5)
            self.sub8(v, 0, store=False)
            self.hl = (self.hl + step) & 0xFFFF
            self.bc = (self.bc - 1) & 0xFFFF
            if repeat and self.bc and not self.zf:
                self.idle(self.hl - step, 5)
                self.pc = (self.pc - 2) & 0xFFFF
            self.pf = self.bc != 0
            return
        raise Unsupported("opcode #ED%02X at #%04X" % (op, self.pc - 2))

    # -- DD / FD prefix -----------------------------------------------------
    def op_index(self, prefix):
        name = "ix" if prefix == 0xDD else "iy"
        idx = getattr(self, name)
        op = self.fetch_op()
        self.idle_ir(T_INT[op])                 # the same as the HL form, plus the prefix

        if op == 0x21:
            return setattr(self, name, self.fetchw())
        if op == 0x22:
            return self.ww(self.fetchw(), idx)
        if op == 0x2A:
            return setattr(self, name, self.rw(self.fetchw()))
        if op == 0x23:
            return setattr(self, name, (idx + 1) & 0xFFFF)
        if op == 0x2B:
            return setattr(self, name, (idx - 1) & 0xFFFF)
        if op == 0xE5:
            return self.push(idx)
        if op == 0xE1:
            return setattr(self, name, self.pop())
        if op == 0xE9:
            self.pc = idx
            return
        if op == 0xF9:
            self.sp = idx
            return
        if op & 0xCF == 0x09:                           # add ix,rr
            rp = (op >> 4) & 3
            v = (self.bc, self.de, idx, self.sp)[rp]
            return setattr(self, name, self.add16(idx, v))
        # (ix+d): the displacement is read, then five T with its address
        # still on the bus while the sum is formed - except where an operand
        # follows it, which overlaps two of them.
        if op == 0x36:                                  # ld (ix+d),n: 19 T
            d = self.fetchd()
            n = self.fetch()
            self.idle(self.pc - 1, 2)
            return self.wb(idx + d, n)
        if op in (0x34, 0x35):                          # inc/dec (ix+d): 23 T
            d = self.fetchd()
            self.idle(self.pc - 1, 5)
            v = self.rb(idx + d)
            self.idle(idx + d, 1)
            return self.wb(idx + d, self.inc8(v) if op == 0x34 else self.dec8(v))
        if op >> 6 == 1 and (op & 7) == 6 and op != 0x76:       # ld r,(ix+d): 19 T
            d = self.fetchd()
            self.idle(self.pc - 1, 5)
            return self.s8((op >> 3) & 7, self.rb(idx + d))
        if op >> 6 == 1 and ((op >> 3) & 7) == 6:               # ld (ix+d),r: 19 T
            d = self.fetchd()
            self.idle(self.pc - 1, 5)
            return self.wb(idx + d, self.r[op & 7])
        if op >> 6 == 2 and (op & 7) == 6:                      # alu a,(ix+d): 19 T
            d = self.fetchd()
            self.idle(self.pc - 1, 5)
            return self.alu((op >> 3) & 7, self.rb(idx + d))
        if op == 0xCB:                                  # DD CB d op
            # The displacement comes before the opcode in this group, which is
            # the only place in the instruction set where that happens.
            d = self.fetchd()
            sub = self.fetch()                          # a read, not an M1
            self.idle(self.pc - 1, 2)                   # 20 T for BIT, 23 for the rest
            addr = (idx + d) & 0xFFFF
            hi, reg, bit = sub >> 6, sub & 7, (sub >> 3) & 7
            v = self.rb(addr)
            self.idle(addr, 1)
            if hi == 1:                                 # bit n,(ix+d)
                self.zf = not (v & (1 << bit))
                self.pf = self.zf
                self.sf = bit == 7 and not self.zf
                self.hf = True
                self.nf = False
                return
            if hi == 0:
                v = self.rot(bit, v)
            elif hi == 2:
                v &= ~(1 << bit)
            else:
                v |= 1 << bit
            self.wb(addr, v)
            if reg != 6:
                self.s8(reg, v)                         # the undocumented copy
            return
        # With a DD/FD prefix, a register code of 4 or 5 is not H or L but the
        # high or low half of the index register. Undocumented, but every Z80
        # ever made does it, and the Arkos player is one of the many things
        # that uses it.
        def half(i, v=None):
            cur = getattr(self, name)
            if i not in (4, 5):
                if v is None:
                    return self.r[i]
                self.r[i] = v & 0xFF
                return None
            if v is None:
                return (cur >> 8) if i == 4 else (cur & 0xFF)
            if i == 4:
                setattr(self, name, ((v & 0xFF) << 8) | (cur & 0xFF))
            else:
                setattr(self, name, (cur & 0xFF00) | (v & 0xFF))
            return None

        dst, src = (op >> 3) & 7, op & 7
        if op & 0xC7 == 0x06 and dst != 6:                      # ld ixh/ixl,n
            return half(dst, self.fetch())
        if op >> 6 == 1 and dst != 6 and src != 6:              # ld r,r'
            return half(dst, half(src))
        if op & 0xC7 == 0x04 and dst != 6:                      # inc ixh/ixl
            return half(dst, self.inc8(half(dst)))
        if op & 0xC7 == 0x05 and dst != 6:                      # dec ixh/ixl
            return half(dst, self.dec8(half(dst)))
        if op >> 6 == 2 and src != 6:                           # alu a,ixh/ixl
            return self.alu(dst, half(src))

        raise Unsupported("opcode #%02X%02X at #%04X" % (prefix, op, self.pc - 2))


# ---------------------------------------------------------------------------
# The ULA: the keyboard, the border, the beeper
# ---------------------------------------------------------------------------

# The keyboard is eight half-rows of five keys. A read of port #FE puts the
# half-rows wanted as zeros on A8-A15, and a pressed key reads 0.
#   A8 CAPS Z X C V   A9 A S D F G   A10 Q W E R T   A11 1 2 3 4 5
#   A12 0 9 8 7 6     A13 P O I U Y  A14 ENTER L K J H  A15 SPACE SYM M N B
_HALF_ROWS = (("CAPS", "Z", "X", "C", "V"), ("A", "S", "D", "F", "G"),
              ("Q", "W", "E", "R", "T"), ("1", "2", "3", "4", "5"),
              ("0", "9", "8", "7", "6"), ("P", "O", "I", "U", "Y"),
              ("ENTER", "L", "K", "J", "H"), ("SPACE", "SYM", "M", "N", "B"))
KEY_MATRIX = {name: [(row, bit)] for row, names in enumerate(_HALF_ROWS)
              for bit, name in enumerate(names)}
# The game's controls by what they do (loukspeccy48.md section 6.4), so a
# route reads the same as it did on the CPC.
for _alias, _key in (("LEFT", "O"), ("RIGHT", "P"), ("UP", "Q"), ("DOWN", "A"),
                     ("FIRE", "SPACE")):
    KEY_MATRIX[_alias] = KEY_MATRIX[_key]
KEY_MATRIX["BREAK"] = KEY_MATRIX["CAPS"] + KEY_MATRIX["SPACE"]

# Kempston bits, for KJ_ names: right left down up fire.
KEMPSTON = {"KJ_RIGHT": 0, "KJ_LEFT": 1, "KJ_DOWN": 2, "KJ_UP": 3, "KJ_FIRE": 4}


class ZXIO:
    def __init__(self, keys=(), kempston=False):
        self.keys = keys            # (name, first frame, last frame)
        self.kempston = kempston
        self.clock = 0
        self.border = None
        self.border_changes = 0
        self.speaker = 0
        self.speaker_flips = 0
        self.speaker_log = None     # T-state and border of every flip, if kept
        self.key_reads = 0
        self.mem = None             # for the floating bus
        self.ay = None              # sixteen registers, on a 128K
        self.ay_reg = 0
        self.ay_log = None          # T-state, register, value of each write

    def frame(self):
        return self.clock // T_FRAME

    def held(self):
        now = self.frame()
        return [name for name, first, last in self.keys if first <= now <= last]

    def out(self, port, val):
        if self.ay is not None and port & 0x8002 == 0x8000:
            if port & 0x4000:
                self.ay_reg = val & 0x0F
            else:
                self.ay[self.ay_reg] = val
                if self.ay_log is not None:
                    self.ay_log.append((self.clock, self.ay_reg, val))
            return
        if not port & 1:
            if self.border != val & 7:
                self.border_changes += 1
            self.border = val & 7
            s = (val >> 4) & 1
            if s != self.speaker:
                self.speaker_flips += 1
                if self.speaker_log is not None:
                    self.speaker_log.append((self.clock, val & 7))
            self.speaker = s

    def inp(self, port):
        if self.ay is not None and port & 0xC002 == 0xC000:
            return self.ay[self.ay_reg]
        if not port & 1:
            self.key_reads += 1
            rows = 0x1F
            for name in self.held():
                for row, bit in KEY_MATRIX.get(name, ()):
                    if not port & (0x100 << row):
                        rows &= ~(1 << bit)
            return 0xE0 | rows
        if port & 0xE0 == 0 and self.kempston:  # Kempston: A5-A7 low
            v = 0
            for name in self.held():
                if name in KEMPSTON:
                    v |= 1 << KEMPSTON[name]
            return v
        return self.floating()

    def floating(self):
        """What nothing answering a port reads: the ULA's fetch, if any."""
        if self.mem is None:
            return 0xFF
        tf = self.clock % T_FRAME - T_CONTEND
        if tf < 0 or tf >= 192 * T_PER_LINE:
            return 0xFF
        y, pos = divmod(tf, T_PER_LINE)
        if pos >= 128 or pos & 7 >= 4:
            return 0xFF
        col = (pos >> 3) * 2 + ((pos & 7) >> 1)
        if pos & 1:
            return self.mem[0x5800 + (y >> 3) * 32 + col]
        return self.mem[line_addr(y) + col]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

# The 48K's colours, normal then BRIGHT.
PALETTE = [
    (0x00, 0x00, 0x00), (0x00, 0x00, 0xD7), (0xD7, 0x00, 0x00), (0xD7, 0x00, 0xD7),
    (0x00, 0xD7, 0x00), (0x00, 0xD7, 0xD7), (0xD7, 0xD7, 0x00), (0xD7, 0xD7, 0xD7),
    (0x00, 0x00, 0x00), (0x00, 0x00, 0xFF), (0xFF, 0x00, 0x00), (0xFF, 0x00, 0xFF),
    (0x00, 0xFF, 0x00), (0x00, 0xFF, 0xFF), (0xFF, 0xFF, 0x00), (0xFF, 0xFF, 0xFF),
]
COLOUR = "KBRMGCYW"
BORDER = 32


def line_addr(y):
    """#4000 | y7 y6 | y2 y1 y0 | y5 y4 y3 | x4..x0"""
    return 0x4000 | ((y & 0xC0) << 5) | ((y & 7) << 8) | ((y & 0x38) << 2)


def screen_colours(mem):
    """A grid of palette indices, 256x192, FLASH shown in its first phase."""
    rows = []
    for y in range(192):
        a = line_addr(y)
        line = []
        for cx in range(32):
            bits = mem[a + cx]
            attr = mem[0x5800 + (y >> 3) * 32 + cx]
            br = 8 if attr & 0x40 else 0
            ink, paper = (attr & 7) + br, ((attr >> 3) & 7) + br
            line += [ink if bits & (0x80 >> b) else paper for b in range(8)]
        rows.append(line)
    return rows


def write_png(rows, border, path, scale):
    try:
        from PIL import Image
    except ImportError:
        sys.exit("--png needs Pillow (pip install pillow); try --ascii instead")
    w, h = 256 + 2 * BORDER, 192 + 2 * BORDER
    img = Image.new("RGB", (w, h), PALETTE[border or 0])
    px = img.load()
    for y, line in enumerate(rows):
        for x, c in enumerate(line):
            px[BORDER + x, BORDER + y] = PALETTE[c]
    if scale != 1:
        img = img.resize((w * scale, h * scale), Image.NEAREST)
    img.save(path)
    return img.size


def write_ascii(mem):
    """One character a cell: the ink's letter where the cell has any ink set,
    the paper's where it is empty, upper case when BRIGHT, * when FLASH."""
    out = []
    for r in range(24):
        line = []
        for c in range(32):
            attr = mem[0x5800 + r * 32 + c]
            inked = any(mem[line_addr(r * 8 + k) + c] for k in range(8))
            ch = COLOUR[attr & 7] if inked else COLOUR[(attr >> 3) & 7]
            if not attr & 0x40:
                ch = ch.lower()
            line.append("*" if attr & 0x80 else ch)
        out.append("%2d %s" % (r, "".join(line)))
    return "\n".join(out)


# ---------------------------------------------------------------------------

def debris_ref(mem, d):
    """What the room should look like right now, outside the cast: painted by
    tools/zxroomcheck.py from the tables in memory, with the pickups that are
    still there and the way out as it is drawn. Repainted only when one of
    those changes."""
    import zxroomcheck
    s = d["sym"]
    n = mem[s["CUR_ROOM"]]
    rec = s["ROOMS"] + n * s["R_SIZE"]
    nsaus = mem[rec + s["R_NSAUS"]]
    pend = [mem[s["PICK_PEND"] + 4 * k + 2] | mem[s["PICK_PEND"] + 4 * k + 3] << 8
            for k in range(mem[s["PICK_PEND_N"]])]
    alive = [bool(mem[s["SAUSAGE_ALIVE"] + k]) or
             s["PICK_BUFS"] + k * s["PICK_BUF"] in pend for k in range(nsaus)]
    if mem[rec + s["R_MILKX"]] != s["NO_MILK"]:
        alive.append(bool(mem[s["MILK_ALIVE"]]) or s["MILK_BUF"] in pend)
    if mem[s["EXIT_PENDING"]]:
        return None                     # the door is being painted open
    opened = bool(mem[s["LEVEL_DONE"]])
    key = (n, opened, tuple(alive))
    if d.get("ref_key") != key:
        t = zxroomcheck.Tables(None, s, mem=bytes(mem))
        d["ref_key"] = key
        d["ref"] = zxroomcheck.paint(t, n, opened, alive)[0].bytes()
    return d["ref"]


def debris_rects(mem, d):
    """Where every sprite's picture is standing at this instant - cat_ox and
    E_OX, not where it is going - as byte columns and scanlines. A sprite
    keeps the cells it covers, so that is the ground it owns."""
    out = []

    def rect(ox, oy, spr):
        h, wb = mem[spr + 1], mem[spr + 2]
        return (ox >> 2, oy, wb, h)
    if mem[d["cat_drawn"]]:
        spr = mem[d["cat_ospr"]] | mem[d["cat_ospr"] + 1] << 8
        out.append(rect(mem[d["cat_ox"]], mem[d["cat_oy"]], spr))
    for i in range(d["enemy_count"]):
        b = d["enemies"] + i * d["e_size"]
        if mem[b + d["e_type"]] and mem[b + d["e_drawn"]]:
            spr = mem[b + d["e_ospr"]] | mem[b + d["e_ospr"] + 1] << 8
            out.append(rect(mem[b + d["e_ox"]], mem[b + d["e_oy"]], spr))
    return out


def debris_scan(mem, d, frame):
    """Anything on the screen, outside every sprite's cells, that is not the
    room as it should be by now: a piece of something lifted off in the wrong
    order and left there for good, or a change to the room made while
    somebody was standing in it."""
    if not mem[d["room_ready"]] or mem[d["game_over"]]:
        return                          # being painted, or under a banner
    ref = debris_ref(mem, d)
    if ref is None:
        return
    rects = debris_rects(mem, d)
    top = d["play_top"]

    def covered(c, y0, y1):
        return any(rx <= c < rx + rw and ry < y1 and y0 < ry + rh
                   for rx, ry, rw, rh in rects)
    stray = []
    for y in range(top, 192):
        a = line_addr(y)
        for c in range(32):
            if mem[a + c] != ref[a - 0x4000 + c] and not covered(c, y, y + 1):
                stray.append((c, y))
    for i in range((top >> 3) * 32, 768):
        if mem[0x5800 + i] != ref[6144 + i]:
            c, r = i & 31, i >> 5
            if not covered(c, r * 8, r * 8 + 8):
                stray.append((c, r * 8))
    d["frames"] += 1
    if stray and os.environ.get("DEBRIS_VERBOSE"):
        print("  frame %3d  %d stray  %s  rects %s  ref %s"
              % (frame, len(stray), stray[:8], rects, d.get("ref_key")))
    if len(stray) > d["worst"]:
        xs = [x for x, _ in stray]
        ys = [y for _, y in stray]
        d.update(worst=len(stray), worst_frame=frame,
                 where=(min(xs), max(xs), min(ys), max(ys)))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("binary", help="raw assembled code (make bin)")
    ap.add_argument("--org", default="0x8000", help="load address (default 0x8000)")
    ap.add_argument("--entry", help="start address, if not the load address")
    ap.add_argument("--rom", help="16K ROM image for #0000-#3FFF; without it "
                    "the ROM area reads zero. Writes there are ignored either way")
    ap.add_argument("--png", help="write the screen here, border and all")
    ap.add_argument("--scale", type=int, default=2, help="PNG pixel scale (default 2)")
    ap.add_argument("--ascii", action="store_true",
                    help="print the screen a cell a character: the ink's colour "
                         "where the cell has ink in it, the paper's where it is "
                         "empty, upper case when BRIGHT")
    ap.add_argument("--dump", help="write the screen here as a 6912-byte SCREEN$")
    ap.add_argument("--keys", default="",
                    help="keys held down, comma separated. NAME is held the "
                         "whole run, NAME@12 from frame 12 on, NAME@12-14 for "
                         "those frames only - e.g. FIRE@12-13,RIGHT@15. Keys are "
                         "named as on the keyboard (Q, SPACE, CAPS, SYM, ENTER), "
                         "or as the game's controls (LEFT, RIGHT, UP, DOWN, FIRE, "
                         "BREAK), or KJ_LEFT.. KJ_FIRE for a Kempston")
    ap.add_argument("--kempston", action="store_true",
                    help="a Kempston interface is plugged in; without it port "
                         "#1F reads #FF")
    ap.add_argument("--sym", help="rasm symbol file (rasm -s -sa -os ...)")
    ap.add_argument("--watch", default="",
                    help="comma separated symbols to print once per frame, "
                         "optionally with a byte offset (enemies+8); suffix "
                         ":w for a 16-bit value, :s for signed 16-bit")
    ap.add_argument("--frames", type=int, default=0,
                    help="stop after this many frames (0 = only on a self-jump "
                         "or a HALT with interrupts off)")
    ap.add_argument("--play", action="store_true",
                    help="straight into the game on hard, past the title and "
                         "the difficulty: pokes title_skip (needs --sym). Every "
                         "scripted run of a room uses it, so its frames are "
                         "the ones it had before there was a title")
    ap.add_argument("--model", choices=sorted(MODELS), default="48",
                    help="the 48K, or the 128K and +2's frame")
    ap.add_argument("--ay-log", metavar="FILE",
                    help="--model 128: every write to the AY, as T-state, "
                         "register and value, a line each")
    ap.add_argument("--mark", default="", metavar="SYM,SYM",
                    help="print the frame and T-state every time the program "
                         "gets to one of these, from --mark-from on")
    ap.add_argument("--mark-from", type=int, default=0, metavar="FRAME")
    ap.add_argument("--stop-at", metavar="SYM",
                    help="stop the first time the program gets to this address")
    ap.add_argument("--start-t", type=int, default=0,
                    help="T-state into the frame the program starts at (the "
                         "ROM's USR call lands anywhere)")
    ap.add_argument("--profile", action="store_true",
                    help="T-states spent in each named routine (needs --sym)")
    ap.add_argument("--profile-from", type=int, default=0, metavar="FRAME",
                    help="start counting at this frame")
    ap.add_argument("--save-mem", action="append", default=[],
                    metavar="ADDR:LEN=FILE",
                    help="write a range of memory out when the run ends")
    ap.add_argument("--beam", action="store_true",
                    help="where the beam is when each sprite is drawn (needs "
                         "--sym). Every sprite has to be back on the screen "
                         "before the beam reaches it, and this says whether "
                         "it was")
    ap.add_argument("--beam-from", type=int, default=40,
                    help="first frame to report for --beam")
    ap.add_argument("--speaker", metavar="FILE",
                    help="write the T-state of every flip of the beeper, and "
                         "the border colour the same OUT wrote, one to a line")
    ap.add_argument("--debris", action="store_true",
                    help="watch for ink left behind on ground the room "
                         "painted empty (needs --sym)")
    ap.add_argument("--debris-from", type=int, default=30,
                    help="first frame to watch for --debris")
    ap.add_argument("--trap", help="symbol or address; report the first write "
                                   "to it and where it came from")
    ap.add_argument("--trap-value", help="only trap a write of this byte value")
    ap.add_argument("--sp-floor", help="report the first push below this address")
    ap.add_argument("--trap-frame", type=int, help="ignore trap hits before this frame")
    ap.add_argument("--poke", action="append", default=[], metavar="SYM=N@FRAME",
                    help="write a byte into memory at the top of a frame: "
                         "--poke cat_lives=7@200")
    ap.add_argument("--max-steps", type=int, default=50_000_000)
    args = ap.parse_args()

    keys = []
    for item in args.keys.split(","):
        item = item.strip().upper()
        if not item:
            continue
        name, _, when = item.partition("@")
        if name not in KEY_MATRIX and name not in KEMPSTON:
            sys.exit("z80check: no such key %r (have %s)"
                     % (name, ", ".join(sorted(list(KEY_MATRIX) + list(KEMPSTON)))))
        first, last = 0, 1 << 30
        if when:
            lo, dash, hi = when.partition("-")
            try:
                first = int(lo)
                last = int(hi) if dash else 1 << 30
            except ValueError:
                sys.exit("z80check: bad frame range in %r" % item)
        keys.append((name, first, last))

    symbols = {}
    if args.sym:
        for line in open(args.sym):
            parts = line.split()
            if len(parts) >= 2 and parts[1].startswith("#"):
                symbols[parts[0].upper()] = int(parts[1][1:], 16)

    def address(text):
        """A symbol, a number, or either plus or minus a number: rooms+21."""
        for sep in ("+", "-"):
            if sep in text[1:]:
                base, _, off = text.partition(sep)
                return (address(base) + int(off, 0) * (1 if sep == "+" else -1)) & 0xFFFF
        return symbols[text.upper()] if text.upper() in symbols else int(text, 0)

    watch = []
    for item in args.watch.split(","):
        item = item.strip()
        if not item:
            continue
        name, _, kind = item.partition(":")
        if not args.sym:
            sys.exit("z80check: --watch needs --sym")
        base, offset = name, 0
        for sep in ("+", "-"):
            if sep in name:
                base, _, off = name.partition(sep)
                try:
                    offset = int(off, 0) * (1 if sep == "+" else -1)
                except ValueError:
                    sys.exit("z80check: bad offset in %r" % name)
                break
        if base.upper() not in symbols:
            sys.exit("z80check: %r is not in %s" % (base, args.sym))
        watch.append((name, symbols[base.upper()] + offset, kind or "b"))

    org = address(args.org)
    code = open(args.binary, "rb").read()
    mem = bytearray(0x10000)
    if args.rom:
        rom = open(args.rom, "rb").read()
        mem[0:len(rom)] = rom[:0x4000]
    mem[org:org + len(code)] = code

    set_model(args.model)
    io = ZXIO(keys, args.kempston)
    io.mem = mem
    if args.model == "128":
        io.ay = [0] * 16
        if args.ay_log:
            io.ay_log = []
    if args.speaker:
        io.speaker_log = []
    cpu = Z80(mem, io)
    cpu.rom_top = 0x4000
    if args.trap:
        cpu.trap = address(args.trap)
        if args.trap_value:
            cpu.trap_value = int(args.trap_value, 0) & 0xFF
        if args.trap_frame:
            cpu.trap_frame = args.trap_frame
    if args.sp_floor:
        cpu.sp_floor = int(args.sp_floor, 0)
    cpu.pc = address(args.entry) if args.entry else org
    cpu.sp = 0x5CFE                             # wherever BASIC left it
    cpu.imode = 1
    cpu.i = 0x3F
    cpu.t = args.start_t % T_FRAME

    t_budget = args.frames * T_FRAME if args.frames else None
    limit = args.max_steps
    irqs = 0
    reason = "instruction budget"
    last_frame = -1
    trace = []

    prof = None
    if args.profile:
        if not symbols:
            sys.exit("--profile needs --sym")
        prof_addr = sorted(set(symbols.values()))
        prof_name = {v: k for k, v in sorted(symbols.items(), reverse=True)}
        prof = dict.fromkeys(prof_addr, 0)
        prof_start = args.profile_from * T_FRAME

    beam = None
    if args.beam:
        if not symbols:
            sys.exit("--beam needs --sym")
        want = ("SPR_RESTORE", "SPR_DRAW", "SPRITES_UPDATE_NEXT", "SPR_Y",
                "SPR_H")
        for w in want:
            if w not in symbols:
                sys.exit("--beam needs the symbol %s" % w)
        beam = {"erase": symbols["SPR_RESTORE"], "draw": symbols["SPR_DRAW"],
                "done": symbols["SPRITES_UPDATE_NEXT"],
                "spr_y": symbols["SPR_Y"], "spr_h": symbols["SPR_H"],
                "open": None, "y": 0, "h": 0, "units": []}

    #: frame -> [(address, byte)], applied as that frame starts.
    pokes = {}
    if args.play:
        args.poke = ["title_skip=1@0"] + args.poke
    for item in args.poke:
        where, _, when = item.partition("@")
        name, _, value = where.partition("=")
        pokes.setdefault(int(when), []).append((address(name), int(value, 0) & 0xFF))

    failed = False
    debris = None
    if args.debris:
        if not symbols:
            sys.exit("--debris needs --sym")
        want = ("WAIT_RENDER", "LINE_TAB", "CAT_DRAWN", "CAT_OX", "CAT_OY", "CAT_OSPR",
                "ENEMIES", "ENEMY_COUNT", "E_SIZE", "E_TYPE", "E_DRAWN",
                "E_OX", "E_OY", "E_OSPR", "ROOM_READY", "PLAY_TOP", "GAME_OVER")
        for w in want:
            if w not in symbols:
                sys.exit("--debris needs the symbol %s" % w)
        debris = {w.lower(): symbols[w] for w in want}
        debris.update(sym=symbols, worst=0, worst_frame=0, where=None, frames=0)

    steps = 0
    accepted_in = -1                            # the frame whose INT was taken
    stop_at = address(args.stop_at) if args.stop_at else None
    marks = {address(m): m for m in args.mark.split(",") if m}
    while steps < limit:
        if cpu.pc == stop_at:
            reason = "got to %s" % args.stop_at
            break
        io.clock = cpu.t
        if t_budget is not None and cpu.t >= t_budget:
            reason = "frame budget"
            break
        f = cpu.t // T_FRAME
        if marks and cpu.pc in marks and f >= args.mark_from:
            print("  frame %3d  T %5d  %s" % (f, cpu.t % T_FRAME, marks[cpu.pc]))
        if beam is not None:
            if cpu.pc == beam["erase"]:
                beam["open"] = cpu.t
            elif cpu.pc == beam["draw"] and beam["open"] is not None:
                beam["y"] = mem[beam["spr_y"]]
                beam["h"] = mem[beam["spr_h"]]
            elif cpu.pc == beam["done"] and beam["open"] is not None:
                beam["units"].append((beam["y"], beam["h"],
                                      beam["open"], cpu.t))
                beam["open"] = None
        if pokes:
            for addr, value in pokes.pop(f, ()):
                mem[addr] = value
                print("  frame %3d  poked #%04X = %d" % (f, addr, value))
        # Once a frame, where the loop has finished a picture and is waiting
        # for the next: a frame the game overruns is otherwise looked at with
        # half its cast laid down and the other half not yet.
        if (debris is not None and cpu.pc == debris["wait_render"]
                and f != debris.get("last")):
            debris["last"] = f
            if f >= args.debris_from:
                debris["pc"] = cpu.pc
                debris_scan(mem, debris, f)
        if watch and f != last_frame:
            last_frame = f
            cells = []
            for name, addr, kind in watch:
                if kind == "b":
                    cells.append("%s=%d" % (name, mem[addr]))
                else:
                    v = mem[addr] | (mem[addr + 1] << 8)
                    if kind == "s" and v > 32767:
                        v -= 65536
                    cells.append("%s=%d" % (name, v))
            trace.append("  frame %3d  %s" % (f, "  ".join(cells)))

        # The ULA holds INT for the first 32 T of the frame. The CPU looks at
        # it at the end of each instruction, and not at all straight after an
        # EI; one held through a whole DI is simply missed.
        if cpu.halted:
            if not cpu.iff:
                reason = "HALT with interrupts off"
                break
            if cpu.t % T_FRAME >= INT_LENGTH or accepted_in == f:
                # a halted Z80 runs NOPs until the interrupt; skip them, 4 T
                # at a time so the phase stays what it would have been
                n = -(-((f + 1) * T_FRAME - cpu.t) // 4)
                cpu.t += 4 * n
                continue
        if (cpu.iff and not cpu.ei_pending and cpu.t % T_FRAME < INT_LENGTH
                and accepted_in != f):
            accepted_in = f
            cpu.halted = False
            cpu.iff = False
            cpu.t += 7                          # the acknowledge: a long M1
            cpu.push(cpu.pc)
            if cpu.imode == 2:
                cpu.pc = cpu.rw((cpu.i << 8) | 0xFF)    # nothing on the bus: #FF
            else:
                cpu.pc = 0x38
            irqs += 1
            continue

        op = mem[cpu.pc]
        if op == 0x18 and mem[(cpu.pc + 1) & 0xFFFF] == 0xFE:
            reason = "self-jump"
            break
        if op == 0xC3 and (mem[(cpu.pc + 1) & 0xFFFF] |
                           mem[(cpu.pc + 2) & 0xFFFF] << 8) == cpu.pc:
            reason = "self-jump"
            break
        prof_in = None
        if prof is not None and cpu.t >= prof_start:
            i = bisect.bisect_right(prof_addr, cpu.pc) - 1
            if i >= 0:
                prof_in = prof_addr[i]
        t_before = cpu.t
        was_pending = cpu.ei_pending
        try:
            cpu.step()
        except Unsupported as e:
            sys.exit("z80check: %s - not implemented" % e)
        if was_pending:
            cpu.ei_pending = False
        if prof_in is not None:
            prof[prof_in] += cpu.t - t_before
        steps += 1
    else:
        if not args.frames and stop_at is None:
            sys.exit("z80check: still running after %d instructions" % limit)
        reason = "instruction ceiling"

    for spec in args.save_mem:
        where, _, path = spec.partition("=")
        addr, _, length = where.partition(":")
        addr = address(addr)
        length = int(length, 0)
        open(path, "wb").write(bytes(mem[addr:addr + length]))
        print("wrote %s (%d bytes from #%04X)" % (path, length, addr))

    if cpu.sp_hit:
        print("STACK SP reached #%04X on frame %d, at PC #%04X"
              % (cpu.sp_hit[1], cpu.sp_hit[2], cpu.sp_hit[0]))
    if cpu.big_ldir:
        pc, n, src, dst, ret = cpu.big_ldir
        print("LDIR  %d bytes at PC #%04X, HL=#%04X DE=#%04X - a length that "
              "wrapped? Return address on the stack #%04X"
              % (n, pc, src, dst, ret))
    if cpu.trap is not None:
        if cpu.trap_hit:
            pc, v, fr, hl, de, bc, sp, ret = cpu.trap_hit
            print("TRAP  #%04X written with #%02X on frame %d, PC after the "
                  "store #%04X" % (cpu.trap, v, fr, pc))
            print("      HL=#%04X DE=#%04X BC=#%04X SP=#%04X, return address "
                  "on the stack #%04X" % (hl, de, bc, sp, ret))
        else:
            print("TRAP  #%04X never written" % cpu.trap)
    if trace:
        print("WATCH")
        print("\n".join(trace))
    print("stopped at #%04X after %d instructions (%s)" % (cpu.pc, steps, reason))
    held = []
    for name, first, last in keys:
        if first == 0 and last > 1 << 20:
            held.append(name)
        elif last > 1 << 20:
            held.append("%s@%d-" % (name, first))
        else:
            held.append("%s@%d-%d" % (name, first, last))
    print("SIM   %d frames, %d interrupts taken, %d keyboard reads%s"
          % (cpu.t // T_FRAME, irqs, io.key_reads,
             ", holding " + " ".join(held) if held else ""))
    print("TIME  T=%d, frame %d at T %d of %d; %d T waited on the ULA"
          % (cpu.t, cpu.t // T_FRAME, cpu.t % T_FRAME, T_FRAME, cpu.waited))
    if args.speaker:
        with open(args.speaker, "w") as fh:
            for t, border in io.speaker_log:
                fh.write("%d %d\n" % (t, border))
    print("ULA   border %s (%d changes), IM %d, I=#%02X, speaker flipped %d times"
          % ("never set" if io.border is None else COLOUR[io.border] + " %d" % io.border,
             io.border_changes, cpu.imode, cpu.i, io.speaker_flips))

    if debris is not None:
        print()
        print("DEBRIS  ink on ground the room painted empty, where no sprite is.")
        if debris["worst"]:
            x0, x1, y0, y1 = debris["where"]
            print("    %d bytes left behind, worst at frame %d, columns %d-%d, lines %d-%d"
                  % (debris["worst"], debris["worst_frame"], x0, x1, y0, y1))
            failed = True
        else:
            print("    %d frames watched, and the room came through every one "
                  "of them clean" % debris["frames"])

    if beam is not None:
        print()
        print("BEAM  a sprite is off the screen from the moment its erase "
              "starts to the moment")
        print("      its redraw finishes. The ULA fetches line y of the picture "
              "at T %d + %dy" % (T_PICTURE, T_PER_LINE))
        print("      of every %d T frame. If that falls inside the window, the "
              "beam draws a hole." % T_FRAME)
        bad = 0
        shown = 0
        for y, h, t0, t1 in beam["units"][args.beam_from:]:
            hit = None
            k = (t0 // T_FRAME) * T_FRAME
            while k <= t1 + T_FRAME:
                for row in range(y, y + h):
                    when = k + T_PICTURE + T_PER_LINE * row
                    if t0 <= when < t1:
                        hit = row
                        break
                if hit is not None:
                    break
                k += T_FRAME
            if hit is not None:
                bad += 1
            if shown < int(os.environ.get("BEAM_SHOW", "12")) and (
                    hit is not None or not os.environ.get("BEAM_HITS")):
                shown += 1
                print("      frame %3d  rows %3d-%-3d rebuilt over %6d T from T %5d - %s"
                      % (t0 // T_FRAME, y, y + h - 1, t1 - t0, t0 % T_FRAME,
                         "caught at row %d" % hit if hit is not None
                         else "clear"))
        print("    %d of %d sprite rebuilds were caught by the beam" %
              (bad, len(beam["units"][args.beam_from:])))

    if prof is not None:
        total = sum(prof.values())
        frames = max(1, cpu.t // T_FRAME - args.profile_from)
        print()
        print("PROFILE  %d T of work over %d frames from frame %d on, which "
              "is %d T a frame of %d. One line is %d T."
              % (total, frames, args.profile_from, total // frames, T_FRAME,
                 T_PER_LINE))
        for addr, n in sorted(prof.items(), key=lambda kv: -kv[1])[:20]:
            if not n:
                break
            print("    %9d T  %6d/frame  %5.1f lines  %5.1f%%  %s"
                  % (n, n // frames, n / frames / T_PER_LINE, 100.0 * n / total,
                     prof_name.get(addr, "#%04X" % addr)))

    if args.ascii:
        print()
        print(write_ascii(mem))
    if args.png:
        size = write_png(screen_colours(mem), io.border, args.png, args.scale)
        print("wrote %s (%dx%d)" % (args.png, size[0], size[1]))
    if args.ay_log and io.ay_log is not None:
        with open(args.ay_log, "w") as f:
            for t, reg, val in io.ay_log:
                f.write("%d %d %d\n" % (t, reg, val))
    if args.dump:
        open(args.dump, "wb").write(bytes(mem[0x4000:0x5B00]))
        print("wrote %s (6912 bytes of screen)" % args.dump)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
