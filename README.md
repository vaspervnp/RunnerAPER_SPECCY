# Runner A.P.E.R — ZX Spectrum

**Runner A.P.E.R** (*Athens Piraeus Electric Railways*) is a top-down endless runner for the **ZX Spectrum 48K**
(and 128K, where the music plays on the AY), written in **Z80 assembly**. It is the Spectrum version of the Amstrad
CPC 6128 game (`../APERRunner`): the game logic is copied from it and adapted; the picture, the sound, the input
and the tape are new.

Run along the three tracks of the electric railway, collect coins, jump over buffer stops, climb onto train roofs
from the ramps and watch out for the signals, from the city avenue all the way to the forest.

> **Status**: complete game (milestones of [planzx.md](planzx.md), in Greek). 25 fps with no torn line at any
> speed (EASY to HARD and TURBO), on 48K and 128K; in the busiest stretches a game frame can still run long and
> take a TV frame more (about 4 TV frames in 1000 on HARD, 17 with TURBO; 30 with TURBO on a 128K): a
> stutter, never a tear.

**Player's manual:** [English](docs/manual_en.md) ([PDF](docs/manual_en.pdf)) ·
[Ελληνικά](docs/manual_el.md) ([PDF](docs/manual_el.pdf))

| | | |
|---|---|---|
| ![Loading](docs/screenshots/01_loading.png) | ![Menu](docs/screenshots/02_menu.png) | ![Running](docs/screenshots/08_running.png) |
| ![Power-up](docs/screenshots/09_power_up.png) | ![Further](docs/screenshots/10_further.png) | ![Hard](docs/screenshots/07_hard_countdown.png) |
| ![Story](docs/screenshots/03_story.png) | ![Menu in Greek](docs/screenshots/06_menu_greek.png) | ![Game over](docs/screenshots/11_game_over.png) |

---

## Features

- **Smooth vertical scroll** at a steady **25 fps** on a machine with no hardware scroll: the world is drawn
  once into a ring in uncontended memory and copied to the screen every game frame behind the beam, by stack
  batches, so no line is ever seen half old, half new.
- **Colour per character cell**: every world row has its attributes, written once a frame in the border gap.
- The CPC's **track generator and chunks**, **3 difficulty levels** (speed 4 / 5 / 6 lines per frame; on HARD you
  also jump the gaps between wagons), trains, ramps, buffer stops, signals.
- **5 heights**: the runner grows the higher he is; **bridges** pass over him.
- **City** (avenue with cars, buses, kiosks) and **forest**, **footbridges** and **road bridges**.
- **Stations** Corinth to Piraeus with platforms, their names on the track; Piraeus gives 1000 points.
- **6 power-ups** (turbo, slow, magnet, super jump, helmet, 2× coins) with their names on the track.
- A **static side HUD** (1/4 of the screen): score, best score, coins, lives, the route, the power-ups with time
  bars.
- **Loading screen**, **menu**, **controls**, **story**, **pause**, **countdown**, **game over** with 3-letter names,
  **high scores**, **demo**; **English and Greek** (`L` in the menu).
- **Sound**: on a 128K the CPC's three tunes and effects on the AY; on a 48K effects on the beeper and the tunes on
  the menu screens.
- **Keyboard, Kempston and Sinclair** joysticks.

Left out from the CPC version (too heavy for the Spectrum's frame): the moving trains and cars, day and night,
the signals' green phase (always red), saving the high scores.

## Controls

| Action | Keyboard | Joystick |
|---|---|---|
| Left lane | `O` | left |
| Right lane | `P` | right |
| Jump | `Q`, `SPACE` or `ENTER` | up / FIRE |
| Fast landing | `A` | down |
| Pause | `H` | — |
| Music on/off | `M` | — |
| Back to the menu | `BREAK` | — |
| Language (menu) | `L` | — |

---

## Requirements

- A **ZX Spectrum 48K** or 128K / +2, or an emulator.
- To build (the same tools as `../LoukoumasSpeccy48`):
  - [rasm](https://github.com/EdouardBERGE/rasm): assembler, on the `PATH`
  - Python 3 + Pillow: graphics, tracks, text, music and tape converters (`tools/`)
  - [FBZX](https://gitlab.com/rastersoft/fbzx): emulator for `make run`
  - for `make check` on the real ROMs: `tools/zxemu/` (floooh/chips `zx.h`, built into `build/libzxheadless.so`)
  - for `make docs`: a headless Chromium (Microsoft Edge of Windows from WSL by default, or `EDGE=...`)

## Build & run

```bash
make
```

builds `build/runner.tap` and `build/runner.tzx` (BASIC loader, loading `SCREEN$`, code) and the snapshots
`build/runner48.z80` and `build/runner128.z80`.

```bash
make run
```

```bash
make check
```

runs the checks: the tape loaded through the real 48K and 128K ROMs, the Z80 interpreter's timing, the world on
the screen against its rows, the picture against the beam at every speed, the world jobs against their time bounds
(slow: several minutes).

```bash
make release
```

puts the tape, the snapshots and the PDF manuals in `release/`.

```bash
make screenshots
```

```bash
make docs
```

On a real Spectrum: `LOAD ""` (48K) or Tape Loader (128K).

## Layout

```
src/       Z80 code (rasm): runner.asm includes the rest
src/data/  generated: graphics, chunks, texts, music
gfx/       the CPC's loading art and logo
levels/    track chunks as text (tools/mklevel.py)
music/     tunes and effects as text (tools/mkmusic.py)
text/      screen texts, English and Greek (tools/mktext.py)
tools/     converters, tape/snapshot makers, the Z80 interpreter and the checks
docs/      manuals (EN/EL, Markdown and PDF), screenshots
build/     generated files
```

## How the picture works

See [planzx.md](planzx.md) (in Greek) for the details. In short: the world lives in a ring of 28 row slots at
`#E400`. Each game frame (2 TV frames, 139 776 T on a 48K) the main loop runs the game logic, the HUD and the
sound, then copies the 24 columns × 192 lines of the playfield from the ring to the screen with `POP`/`PUSH`
batches, starting after the beam has passed the top and staying behind it, drawing the sprites into each
character row as it goes. New rows are generated and drawn into the ring in small jobs, each with a predicted
time bound, fitted around the frame interrupt.

## Thanks

Inspired by the Athens–Piraeus electric railway (Line 1).
