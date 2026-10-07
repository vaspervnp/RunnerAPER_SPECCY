#!/usr/bin/env python3
"""A Spectrum to run the game on from Python: tools/z80check.py's Z80 (its
48K or 128K timing, contention, floating bus and ports), driven a step at a
time so the checks can look at it while it runs.

    m = Machine("build/runner.bin", "build/runner.sym")
    m.run_frames(100)                  # TV frames
    m.peek("cur_j"), m.peekw("cur_top_row")
    m.press("O", frames=4)             # keys as z80check names them
    m.on_pc("blit", fn)                # fn(machine) when the PC gets there
    m.on_screen_write = fn             # fn(t, address, value) for #4000-#5AFF

Nothing here knows the game: the checks in tools/*check.py do.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import z80check  # noqa: E402
from z80check import Z80, ZXIO, Unsupported, KEY_MATRIX, KEMPSTON  # noqa: E402,F401


def symbols(path):
    s = {}
    for line in open(path):
        p = line.split()
        if len(p) >= 2 and p[1].startswith("#"):
            s[p[0].upper()] = int(p[1][1:], 16)
    return s


class _CPU(Z80):
    """The Z80 with a hook on writes to the screen."""
    screen_hook = None

    def wb(self, a, v):
        a &= 0xFFFF
        if self.screen_hook is not None and 0x4000 <= a < 0x5B00:
            self.screen_hook(self.t, a, v & 0xFF)
        Z80.wb(self, a, v)


class Machine:
    def __init__(self, binary, sym, org=None, model="48", entry=None, kempston=False,
                 rom=None, menu=False):
        z80check.set_model(model)
        self.model = model
        self.T_FRAME = z80check.T_FRAME
        self.T_LINE = z80check.T_PER_LINE
        self.T_PICTURE = z80check.T_PICTURE
        self.sym = symbols(sym)
        if org is None:
            org = self.sym.get("BIN_ORG", 0x8000)
        self.mem = bytearray(0x10000)
        if rom:
            data = open(rom, "rb").read()
            self.mem[0:len(data)] = data[:0x4000]
        code = open(binary, "rb").read()
        self.mem[org:org + len(code)] = code
        self.keys = []                          # (name, first frame, last frame)
        self.io = ZXIO(self.keys, kempston)
        self.io.mem = self.mem
        if model == "128":
            self.io.ay = [0] * 16
        self.cpu = _CPU(self.mem, self.io)
        self.cpu.rom_top = 0x4000
        self.cpu.pc = self.addr(entry) if entry is not None else self.sym.get("LOAD_ADDR", org)
        self.cpu.sp = 0x5CFE
        self.cpu.imode = 1
        self.cpu.i = 0x3F
        self.accepted_in = -1
        self.pc_hooks = {}
        self.steps = 0
        if not menu and "BOOT_MODE" in self.sym:   # the game's: straight into
            self.poke("boot_mode", 0)              # a game, not its menu

    # --- symbols and memory ---------------------------------------------------
    def addr(self, name):
        if isinstance(name, int):
            return name
        for sep in ("+", "-"):
            if sep in name[1:]:
                base, _, off = name.partition(sep)
                return (self.addr(base) + int(off, 0) * (1 if sep == "+" else -1)) & 0xFFFF
        if name.upper() in self.sym:
            return self.sym[name.upper()]
        return int(name, 0)

    def peek(self, name, off=0):
        return self.mem[(self.addr(name) + off) & 0xFFFF]

    def peekw(self, name, off=0):
        a = self.addr(name) + off
        return self.mem[a & 0xFFFF] | (self.mem[(a + 1) & 0xFFFF] << 8)

    def peeks(self, name, off=0):
        v = self.peek(name, off)
        return v - 256 if v > 127 else v

    def poke(self, name, value, off=0):
        self.mem[(self.addr(name) + off) & 0xFFFF] = value & 0xFF

    def pokew(self, name, value, off=0):
        a = self.addr(name) + off
        self.mem[a & 0xFFFF] = value & 0xFF
        self.mem[(a + 1) & 0xFFFF] = (value >> 8) & 0xFF

    def block(self, name, n, off=0):
        a = self.addr(name) + off
        return bytes(self.mem[a:a + n])

    # --- time ---------------------------------------------------------------------
    @property
    def t(self):
        return self.cpu.t

    @property
    def frame(self):
        return self.cpu.t // self.T_FRAME

    def on_pc(self, name, fn):
        self.pc_hooks[self.addr(name)] = fn

    @property
    def on_screen_write(self):
        return self.cpu.screen_hook

    @on_screen_write.setter
    def on_screen_write(self, fn):
        self.cpu.screen_hook = fn

    # --- keys -------------------------------------------------------------------------
    def press(self, name, frames=1, start=None):
        """Hold a key (z80check's names, or KJ_ for the Kempston) for TV frames
        from now (or from frame start)."""
        first = self.frame if start is None else start
        self.keys.append((name.upper(), first, first + frames - 1))

    def release_all(self):
        del self.keys[:]

    # --- running ----------------------------------------------------------------------
    def step(self):
        cpu = self.cpu
        io = self.io
        io.clock = cpu.t
        f = cpu.t // self.T_FRAME
        if cpu.halted:
            if not cpu.iff:
                raise RuntimeError("HALT with interrupts off at #%04X" % cpu.pc)
            if cpu.t % self.T_FRAME >= z80check.INT_LENGTH or self.accepted_in == f:
                n = -(-((f + 1) * self.T_FRAME - cpu.t) // 4)
                cpu.t += 4 * n
                return
        if (cpu.iff and not cpu.ei_pending and cpu.t % self.T_FRAME < z80check.INT_LENGTH
                and self.accepted_in != f):
            self.accepted_in = f
            cpu.halted = False
            cpu.iff = False
            cpu.t += 7
            cpu.push(cpu.pc)
            if cpu.imode == 2:
                cpu.pc = cpu.rw((cpu.i << 8) | 0xFF)
            else:
                cpu.pc = 0x38
            return
        hook = self.pc_hooks.get(cpu.pc)
        if hook is not None:
            hook(self)
        was_pending = cpu.ei_pending
        cpu.step()
        if was_pending:
            cpu.ei_pending = False
        self.steps += 1

    def run_until_t(self, t):
        step = self.step
        while self.cpu.t < t:
            step()

    def run_frames(self, n):
        """Run n TV frames from the current one's start."""
        self.run_until_t((self.frame + n) * self.T_FRAME)

    def run_to(self, name, limit_frames=500):
        """Run until the PC is at a symbol (before that instruction runs)."""
        target = self.addr(name)
        end = (self.frame + limit_frames) * self.T_FRAME
        step = self.step
        while self.cpu.pc != target or self.cpu.halted:
            if self.cpu.t >= end:
                raise RuntimeError("never got to %s in %d frames" % (name, limit_frames))
            step()

    # --- the screen -----------------------------------------------------------------------
    def screen(self):
        """The 6912 bytes of the SCREEN$ as it stands."""
        return bytes(self.mem[0x4000:0x5B00])

    def png(self, path, scale=2):
        z80check.write_png(z80check.screen_colours(self.mem), self.io.border or 0, path, scale)


def line_addr(y, x=0):
    return 0x4000 | ((y & 0xC0) << 5) | ((y & 7) << 8) | ((y & 0x38) << 2) | x


def addr_line(a):
    """Bitmap address -> (line, column)."""
    return (((a >> 5) & 0xC0) | ((a >> 8) & 7) | ((a >> 2) & 0x38)), a & 31


def render(scr, path, scale=2, border=0):
    """A SCREEN$ (bytes) to a PNG, through z80check's renderer."""
    mem = bytearray(0x10000)
    mem[0x4000:0x5B00] = scr
    z80check.write_png(z80check.screen_colours(mem), border, path, scale)
