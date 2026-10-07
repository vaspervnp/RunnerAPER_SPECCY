#!/usr/bin/env python3
"""Load a .TAP on a 48K that nobody has to look at, then ask what came out.

    tools/zxcheck.py build/runner.tap --sym build/runner.sym --bin build/runner.bin --png out.png

floooh/chips' zx.h with the real 48K ROM: the ROM boots, LOAD "" is typed at
it, and the ROM's own loader reads the tape (the bit-banging is trapped, see
tools/zxemu/zxheadless.c). So the BASIC tokens, the CLEAR, the USR address and
where the code lands are all tested by the machine that will run them.

Then it checks what any program on the tape has to do: the code landed where
the symbol file says and is the binary that was built, it took IM 2 through
IM2_I, and frame_count counts every frame (irq_handler at least every other one) without a
fetch from the ROM. Exit status 2 means the emulator is not built or the ROM
is missing, which make check reports as skipped. (After the Loukoumas port.)
"""

import argparse
import ctypes
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CHIPS = os.environ.get("CHIPS", os.path.expanduser("~/repos/CPCTools/cpcemu/chips"))
ROM = os.environ.get("ZX48_ROM", "/usr/share/spectrum-roms/48.rom")
ROM128 = [os.environ.get("ZX128_ROM0", "/usr/share/spectrum-roms/128-0.rom"),
          os.environ.get("ZX128_ROM1", "/usr/share/spectrum-roms/128-1.rom")]
LIB = os.path.join(ROOT, "build", "libzxheadless.so")
SRC = os.path.join(HERE, "zxemu", "zxheadless.c")

# The 48K's colours, normal and BRIGHT.
PALETTE = [
    (0x00, 0x00, 0x00), (0x00, 0x00, 0xD7), (0xD7, 0x00, 0x00), (0xD7, 0x00, 0xD7),
    (0x00, 0xD7, 0x00), (0x00, 0xD7, 0xD7), (0xD7, 0xD7, 0x00), (0xD7, 0xD7, 0xD7),
    (0x00, 0x00, 0x00), (0x00, 0x00, 0xFF), (0xFF, 0x00, 0x00), (0xFF, 0x00, 0xFF),
    (0x00, 0xFF, 0x00), (0x00, 0xFF, 0xFF), (0xFF, 0xFF, 0x00), (0xFF, 0xFF, 0xFF),
]


def build_lib():
    if os.path.exists(LIB) and os.path.getmtime(LIB) >= os.path.getmtime(SRC):
        return True
    if not os.path.isdir(CHIPS):
        print("    skipped: floooh/chips not found at %s (set CHIPS)" % CHIPS)
        return False
    os.makedirs(os.path.dirname(LIB), exist_ok=True)
    r = subprocess.run(["gcc", "-O2", "-shared", "-fPIC", "-I", CHIPS, "-o", LIB, SRC])
    return r.returncode == 0


class Zx:
    def __init__(self, roms, kempston=False):
        self.lib = ctypes.CDLL(LIB)
        L = self.lib
        L.zxemu_new_model.restype = ctypes.c_void_p
        L.zxemu_new_model.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        for name in ("zxemu_run_frames", "zxemu_key_down", "zxemu_key_up", "zxemu_watch"):
            getattr(L, name).argtypes = [ctypes.c_void_p, ctypes.c_int]
        L.zxemu_insert_tape.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
        L.zxemu_insert_tape.restype = ctypes.c_bool
        L.zxemu_quickload.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
        L.zxemu_quickload.restype = ctypes.c_bool
        L.zxemu_stop_at.argtypes = [ctypes.c_void_p, ctypes.c_int]
        L.zxemu_stopped.argtypes = [ctypes.c_void_p]
        L.zxemu_stopped.restype = ctypes.c_bool
        L.zxemu_resume.argtypes = [ctypes.c_void_p]
        L.zxemu_read.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_char_p, ctypes.c_int]
        L.zxemu_peek.argtypes = [ctypes.c_void_p, ctypes.c_uint16]
        L.zxemu_peek.restype = ctypes.c_uint8
        for name, rt in (("zxemu_frames", ctypes.c_uint32), ("zxemu_tape_loads", ctypes.c_int),
                         ("zxemu_watch_hits", ctypes.c_uint32),
                         ("zxemu_watch_late", ctypes.c_uint32),
                         ("zxemu_rom_fetches", ctypes.c_uint32),
                         ("zxemu_border", ctypes.c_uint8), ("zxemu_pc", ctypes.c_uint16),
                         ("zxemu_i", ctypes.c_uint8), ("zxemu_im", ctypes.c_uint8)):
            getattr(L, name).argtypes = [ctypes.c_void_p]
            getattr(L, name).restype = rt
        self.h = L.zxemu_new_model(roms[0].encode(),
                                   roms[1].encode() if len(roms) > 1 else None,
                                   1 if kempston else 0)
        if not self.h:
            raise RuntimeError("could not start the Spectrum")

    def __getattr__(self, name):
        f = getattr(self.lib, "zxemu_" + name)
        return lambda *a: f(self.h, *a)

    def type_keys(self, keys, hold=4, gap=10):
        for k in keys:
            self.lib.zxemu_key_down(self.h, ord(k))
            self.lib.zxemu_run_frames(self.h, hold)
            self.lib.zxemu_key_up(self.h, ord(k))
            self.lib.zxemu_run_frames(self.h, gap)

    def mem(self, addr, n):
        buf = ctypes.create_string_buffer(n)
        self.lib.zxemu_read(self.h, addr, buf, n)
        return buf.raw


def read_symbols(path):
    sym = {}
    for line in open(path):
        p = line.split()
        if len(p) >= 2 and p[1].startswith("#"):
            sym[p[0].upper()] = int(p[1][1:], 16)
    return sym


def screen_rgb(scr, border, flash_phase=False):
    """256x192 plus a 32-pixel border, from the 6912 bytes at #4000."""
    W, H, B = 256, 192, 32
    img = [[PALETTE[border]] * (W + 2 * B) for _ in range(H + 2 * B)]
    for y in range(H):
        addr = ((y & 0xC0) << 5) | ((y & 7) << 8) | ((y & 0x38) << 2)
        for cx in range(32):
            bits = scr[addr + cx]
            a = scr[6144 + (y >> 3) * 32 + cx]
            ink, paper, br = a & 7, (a >> 3) & 7, 8 if a & 0x40 else 0
            if a & 0x80 and flash_phase:
                ink, paper = paper, ink
            for b in range(8):
                on = bits & (0x80 >> b)
                img[B + y][B + cx * 8 + b] = PALETTE[(ink if on else paper) + br]
    return img


def save_png(path, img):
    from PIL import Image
    h, w = len(img), len(img[0])
    im = Image.new("RGB", (w, h))
    im.putdata([p for row in img for p in row])
    im.resize((w * 2, h * 2), Image.NEAREST).save(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tap", help="the tape, or with --snapshot the .Z80")
    ap.add_argument("--sym", required=True)
    ap.add_argument("--bin", required=True, help="the binary the code block is")
    ap.add_argument("--blocks", type=int, default=6,
                    help="tape blocks the ROM should read (header + data each)")
    ap.add_argument("--png")
    ap.add_argument("--dump", help="write the screen here as a 6912-byte SCREEN$")
    ap.add_argument("--title", help="and the title screen, before it, here")
    ap.add_argument("--frames", type=int, default=100,
                    help="frames to run once the code has started")
    ap.add_argument("--model", choices=("48", "128"), default="48",
                    help="the 48K, or the 128K through its menu's Tape Loader")
    ap.add_argument("--kempston", action="store_true",
                    help="a Kempston joystick, and SPACE pressed on it as fire")
    ap.add_argument("--snapshot", action="store_true",
                    help="TAP is a .Z80 snapshot: loaded by zx.h, not off a tape")
    ap.add_argument("--loading", metavar="SCR",
                    help="the loading screen the tape should leave up")
    args = ap.parse_args()

    roms = [ROM] if args.model == "48" else ROM128
    for r in roms:
        if not os.path.exists(r):
            print("    skipped: no ROM at %s (set ZX48_ROM, ZX128_ROM0/1)" % r)
            return 2
    if not build_lib():
        return 2

    sym = read_symbols(args.sym)
    zx = Zx(roms, args.kempston)
    zx.run_frames(120)                          # the ROM's RAM test and (c)
    tap = open(args.tap, "rb").read()
    start = sym["LOAD_ADDR"]
    zx.stop_at(start)
    if args.snapshot:
        if not zx.quickload(tap, len(tap)):
            print("    zx.h would not load %s as a %sK snapshot" % (args.tap, args.model))
            return 1
        zx.run_frames(1)
    else:
        zx.insert_tape(tap, len(tap))
        if args.model == "48":
            zx.type_keys('j""\r')               # LOAD "" ENTER
        else:
            zx.run_frames(60)
            zx.type_keys('\r')                  # the menu's first line
        zx.run_frames(300)
    if not zx.stopped():
        print("    the code never started: pc=#%04X after %d tape blocks"
              % (zx.pc(), zx.tape_loads()))
        return 1
    started = zx.frames()
    fails = []
    if args.loading:
        # What is on the screen the moment the code starts is what the
        # tape put there: the SCREEN$, and not a word from the ROM over it.
        same = zx.mem(0x4000, 6912) == open(args.loading, "rb").read()
        print("    the loading screen as the code starts: %s"
              % ("byte for byte the SCREEN$" if same else "NOT the SCREEN$"))
        if not same:
            fails.append("the loading screen was written over")
    # Compared as it starts: the game patches its own code and fills in its
    # sprite records once it is running.
    image = open(args.bin, "rb").read()
    if zx.mem(sym["BIN_ORG"], len(image)) != image:
        fails.append("the code in memory is not %s" % args.bin)
    zx.resume()
    if args.title:
        # The title, with nothing pressed yet: the picture unpacked and the
        # words written on it.
        zx.run_frames(100)
        open(args.title, "wb").write(zx.mem(0x4000, 6912))
    if args.dump and "PLAY_LOOP" in sym:
        # The room as it is painted, before anybody is drawn on it - which
        # is two presses of fire away: past the title, then the difficulty
        # as it stands, which is hard.
        zx.stop_at(sym["PLAY_LOOP"])
        if not args.title:
            zx.run_frames(100)
        zx.type_keys(" ")
        zx.type_keys(" ")
        zx.run_frames(100)
        if not zx.stopped():
            fails.append("the room was never finished")
        open(args.dump, "wb").write(zx.mem(0x4000, 6912))
        zx.resume()
    zx.run_frames(args.frames)
    if args.kempston and "CAT_X" in sym:
        # Right on the stick, which zx.h's Kempston has on cursor right.
        x0 = zx.peek(sym["CAT_X"])
        zx.key_down(0x09)
        zx.run_frames(25)
        zx.key_up(0x09)
        x1 = zx.peek(sym["CAT_X"])
        print("    the stick held right for half a second: the cat from %d to %d"
              % (x0, x1))
        if x1 <= x0:
            fails.append("the cat does not answer the Kempston")

    print("    %sK%s%s:" % (args.model, " with a Kempston" if args.kempston else "",
                         ", from the snapshot" if args.snapshot else ""))
    if args.snapshot:
        print("    the snapshot loaded by zx.h, and the code started at #%04X" % start)
    else:
        print("    the ROM read %d tape blocks and jumped to #%04X at frame %d"
              % (zx.tape_loads(), start, started))
        if zx.tape_loads() != args.blocks:
            fails.append("expected %d tape blocks" % args.blocks)
    if "AY_ON" in sym:
        ay = zx.peek(sym["AY_ON"])
        print("    ay_on=%d: %s" % (ay, "the AY found, the title tune on it" if ay
                                    else "no AY, the title tune on the beeper"))
        if ay != (args.model == "128"):
            fails.append("the AY found where there is none, or missed where there is")
    print("    IM %d, I=#%02X" % (zx.im(), zx.i()))
    if zx.im() != 2 or zx.i() != sym["IM2_I"]:
        fails.append("not IM 2 through #%02X" % sym["IM2_I"])
    # The vector is read from I*256 + whatever is on the bus, which on a 48K
    # is #FF; the emulator is made to put that there. frame_count has to go
    # up once a frame, and nothing may wander into the ROM. The game's blit
    # sits through every other interrupt with them off and counts it itself
    # (src/video.asm), so the handler is entered at least every other frame.
    fc = sym["FRAME_COUNT"]
    a = zx.peek(fc)
    zx.watch(sym["IRQ_HANDLER"])
    zx.run_frames(10)
    b = zx.peek(fc)
    print("    frame_count %d -> %d over ten frames, irq_handler entered %d times,"
          " %d opcodes fetched from the ROM"
          % (a, b, zx.watch_hits(), zx.rom_fetches()))
    if (b - a) & 0xFF != 10 or zx.watch_hits() < 5:
        fails.append("the interrupt did not arrive through irq_handler once a frame")
    if zx.rom_fetches():
        fails.append("the program ran into the ROM")
    # 19 T to take it, plus whatever instruction was in flight. A vector that
    # misses the jump can still get there by sliding through the table, and
    # this is what that looks like.
    print("    at most %d T-states from INT to the handler" % zx.watch_late())
    if zx.watch_late() > 60:
        fails.append("the handler is reached late: the vector misses the jump")

    scr = zx.mem(0x4000, 6912)
    print("    border %d" % zx.border())
    if "ROOM_READY" in sym and not zx.peek(sym["ROOM_READY"]):
        fails.append("the room was never finished")
    if args.png:
        save_png(args.png, screen_rgb(scr, zx.border()))
        print("    wrote %s" % args.png)


    for f in fails:
        print("    FAIL: " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
