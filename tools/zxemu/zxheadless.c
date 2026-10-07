// A headless ZX Spectrum 48K or 128K for make check, on floooh/chips' zx.h.
//
// Flat C API for tools/zxcheck.py (ctypes). Two things on top of zx.h:
//
//   * A tape. The ROM's own LD-BYTES at #0556 is trapped on its opcode fetch
//     and the next .TAP block is handed over directly, the way every emulator
//     does it - so the BASIC loader, its tokens and the CLEAR/USR numbers all
//     go through the real ROM, only the bit-banging is skipped.
//   * Frames counted by the ULA's own interrupt, not by microseconds, so frame
//     n here is frame n of the game.
//
// zx.h does not model contended memory, so nothing here knows how long code
// takes. That is tools/z80check.py's job (milestone 2).
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdalign.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

#define CHIPS_IMPL
#include "chips/chips_common.h"
#include "chips/z80.h"
#include "chips/beeper.h"
#include "chips/ay38910.h"
#include "chips/mem.h"
#include "chips/kbd.h"
#include "chips/clk.h"
#include "systems/zx.h"

#define LD_BYTES 0x0556

typedef struct {
    zx_t zx;
    uint8_t rom[0x4000];
    uint8_t rom1[0x4000];   // the 128K's second ROM, the 48 BASIC one
    uint8_t* tap;
    size_t tap_size;
    size_t tap_pos;
    int tape_loads;
    uint32_t frames;
    uint64_t ticks;
    int watch_pc;           // count opcode fetches here, -1 for none
    uint32_t watch_hits;
    uint32_t rom_fetches;   // opcode fetches below #4000
    uint64_t int_tick;      // when the ULA last raised INT
    uint32_t watch_late;    // the longest from INT to a fetch at watch_pc
    int stop_pc;            // stop the run on an opcode fetch here, -1 for none
    bool stopped;
} emu_t;

static bool load_rom(const char* path, uint8_t* dst) {
    FILE* f = fopen(path, "rb");
    if (!f) { fprintf(stderr, "zxheadless: cannot open %s\n", path); return false; }
    size_t n = fread(dst, 1, 0x4000, f);
    fclose(f);
    if (n != 0x4000) { fprintf(stderr, "zxheadless: %s is not 16K\n", path); return false; }
    return true;
}

// A 48K with rom1 NULL, a 128K with both. joystick: 0 none, 1 Kempston.
// zx.h answers the Kempston port whatever the joystick is, with 0 when there
// is none: it has no floating bus, so it cannot show the game hearing one.
void* zxemu_new_model(const char* rom0, const char* rom1, int joystick) {
    emu_t* e = (emu_t*)calloc(1, sizeof(emu_t));
    if (!e) return NULL;
    if (!load_rom(rom0, e->rom) || (rom1 && !load_rom(rom1, e->rom1))) { free(e); return NULL; }
    zx_desc_t desc;
    memset(&desc, 0, sizeof(desc));
    desc.type = rom1 ? ZX_TYPE_128 : ZX_TYPE_48K;
    desc.joystick_type = joystick ? ZX_JOYSTICKTYPE_KEMPSTON : ZX_JOYSTICKTYPE_NONE;
    desc.audio.beeper_volume = 0.0f;
    if (rom1) {
        desc.roms.zx128_0 = (chips_range_t){ .ptr = e->rom, .size = sizeof(e->rom) };
        desc.roms.zx128_1 = (chips_range_t){ .ptr = e->rom1, .size = sizeof(e->rom1) };
    } else {
        desc.roms.zx48k = (chips_range_t){ .ptr = e->rom, .size = sizeof(e->rom) };
    }
    zx_init(&e->zx, &desc);
    e->watch_pc = -1;
    e->stop_pc = -1;
    return e;
}

void* zxemu_new(const char* rom_path) { return zxemu_new_model(rom_path, NULL, 0); }

void zxemu_free(void* h) {
    emu_t* e = (emu_t*)h;
    if (!e) return;
    free(e->tap);
    free(e);
}

bool zxemu_insert_tape(void* h, const uint8_t* data, size_t size) {
    emu_t* e = (emu_t*)h;
    free(e->tap);
    e->tap = (uint8_t*)malloc(size);
    if (!e->tap) return false;
    memcpy(e->tap, data, size);
    e->tap_size = size;
    e->tap_pos = 0;
    return true;
}

// LD-BYTES: A = the flag byte wanted, IX = where, DE = how many, carry set
// for LOAD and clear for VERIFY. It returns with carry set if it worked.
// Whatever happens, one block of the tape is used up, as on a real one.
static uint64_t tape_trap(emu_t* e) {
    z80_t* c = &e->zx.cpu;
    bool ok = false;
    if (e->tap_pos + 2 <= e->tap_size) {
        size_t len = e->tap[e->tap_pos] | (e->tap[e->tap_pos + 1] << 8);
        const uint8_t* blk = e->tap + e->tap_pos + 2;
        e->tap_pos += 2 + len;
        if (len >= 2 && e->tap_pos <= e->tap_size && blk[0] == c->a) {
            size_t want = c->de;
            size_t have = len - 2;
            size_t count = want < have ? want : have;
            if (c->f & Z80_CF) {
                for (size_t i = 0; i < count; i++) {
                    mem_wr(&e->zx.mem, (uint16_t)(c->ix + i), blk[1 + i]);
                }
            }
            c->ix = (uint16_t)(c->ix + count);
            c->de = (uint16_t)(want - count);
            ok = (count == want);
        }
    }
    if (ok) c->f |= Z80_CF; else c->f &= ~Z80_CF;
    e->tape_loads++;
    // the ROM enables interrupts on the way out of LD-BYTES; then RET
    c->iff1 = c->iff2 = true;
    uint16_t ret = mem_rd(&e->zx.mem, c->sp) | (mem_rd(&e->zx.mem, (uint16_t)(c->sp + 1)) << 8);
    c->sp = (uint16_t)(c->sp + 2);
    return z80_prefetch(c, ret);
}

// One tick at a time, so the trap sees every opcode fetch and the frame count
// sees every interrupt the ULA raises.
static void run(emu_t* e, uint64_t max_ticks, uint32_t until_frames) {
    zx_t* sys = &e->zx;
    uint64_t pins = sys->pins;
    for (uint64_t t = 0; t < max_ticks; t++) {
        uint64_t before = pins;
        pins = _zx_tick(sys, pins);
        e->ticks++;
        // Nothing answers the interrupt acknowledge on a 48K, so the bus
        // floats to #FF, and an IM 2 vector is read from (I*256 + #FF).
        // zx.h leaves whatever was there last, which hides a vector table
        // that only works for some bytes.
        if ((pins & (Z80_M1|Z80_IORQ)) == (Z80_M1|Z80_IORQ)) {
            Z80_SET_DATA(pins, 0xFF);
        }
        if ((pins & Z80_INT) && !(before & Z80_INT)) {
            e->frames++;
            e->int_tick = e->ticks;
            if (until_frames && e->frames >= until_frames) break;
        }
        if ((pins & (Z80_M1|Z80_MREQ|Z80_RD)) == (Z80_M1|Z80_MREQ|Z80_RD)) {
            uint16_t a = Z80_GET_ADDR(pins);
            if (a == e->watch_pc) {
                e->watch_hits++;
                uint64_t late = e->ticks - e->int_tick;
                if (late > e->watch_late) e->watch_late = (uint32_t)late;
            }
            if (a < 0x4000) e->rom_fetches++;
            if (a == e->stop_pc) {
                e->stopped = true;
                e->stop_pc = -1;
                break;
            }
            if (e->tap && a == LD_BYTES && mem_rd(&sys->mem, LD_BYTES) == 0x14) {
                pins = tape_trap(e);
            }
        }
    }
    sys->pins = pins;
    kbd_update(&sys->kbd, 20000);
}

// Run until the ULA has raised n more interrupts.
void zxemu_run_frames(void* h, int n) {
    emu_t* e = (emu_t*)h;
    for (int i = 0; i < n && !e->stopped; i++) {
        run(e, 70908 * 2, e->frames + 1);
    }
}

// Count opcode fetches at one address from now on, and in the ROM.
void zxemu_watch(void* h, int addr) {
    emu_t* e = (emu_t*)h;
    e->watch_pc = addr;
    e->watch_hits = 0;
    e->watch_late = 0;
    e->rom_fetches = 0;
}
uint32_t zxemu_watch_late(void* h) { return ((emu_t*)h)->watch_late; }
uint32_t zxemu_watch_hits(void* h) { return ((emu_t*)h)->watch_hits; }
uint32_t zxemu_rom_fetches(void* h) { return ((emu_t*)h)->rom_fetches; }

// Freeze the machine on the first opcode fetch at addr, before it executes:
// every run after that does nothing until zxemu_resume. Armed before the
// tape is started, because with the loader trapped the whole tape goes in
// inside the frames it takes to type LOAD "".
void zxemu_stop_at(void* h, int addr) {
    emu_t* e = (emu_t*)h;
    e->stop_pc = addr;
    e->stopped = false;
}
bool zxemu_stopped(void* h) { return ((emu_t*)h)->stopped; }
void zxemu_resume(void* h) { ((emu_t*)h)->stopped = false; }

// A .Z80 snapshot, through zx.h's own loader: the machine as it describes,
// running from its PC.
bool zxemu_quickload(void* h, const uint8_t* data, size_t size) {
    emu_t* e = (emu_t*)h;
    return zx_quickload(&e->zx, (chips_range_t){ .ptr = (void*)data, .size = size });
}

uint32_t zxemu_frames(void* h) { return ((emu_t*)h)->frames; }
uint64_t zxemu_ticks(void* h) { return ((emu_t*)h)->ticks; }
int zxemu_tape_loads(void* h) { return ((emu_t*)h)->tape_loads; }

void zxemu_key_down(void* h, int key) { zx_key_down(&((emu_t*)h)->zx, key); }
void zxemu_key_up(void* h, int key) { zx_key_up(&((emu_t*)h)->zx, key); }

uint8_t zxemu_peek(void* h, uint16_t addr) { return mem_rd(&((emu_t*)h)->zx.mem, addr); }
void zxemu_poke(void* h, uint16_t addr, uint8_t v) { mem_wr(&((emu_t*)h)->zx.mem, addr, v); }

void zxemu_read(void* h, uint16_t addr, uint8_t* dst, int len) {
    emu_t* e = (emu_t*)h;
    for (int i = 0; i < len; i++) dst[i] = mem_rd(&e->zx.mem, (uint16_t)(addr + i));
}

uint8_t zxemu_border(void* h) { return ((emu_t*)h)->zx.border_color; }
uint16_t zxemu_pc(void* h) { return ((emu_t*)h)->zx.cpu.pc; }
uint8_t zxemu_i(void* h) { return ((emu_t*)h)->zx.cpu.i; }
uint8_t zxemu_im(void* h) { return ((emu_t*)h)->zx.cpu.im; }
