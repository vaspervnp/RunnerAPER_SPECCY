# Runner A.P.E.R - ZX Spectrum 48K. Build with rasm
# (https://github.com/EdouardBERGE/rasm) and Python 3.
#
#   make              the game on tape (.tap and .tzx) and as snapshots (.z80,
#                     48K and 128K)
#   make run          the tape in FBZX
#   make release      those in release/, with the manuals
#   make screenshots  docs/screenshots/*.png from the game on tools/zxrun.py
#   make docs         docs/manual_*.pdf (a headless Edge/Chromium: EDGE=...)
#   make m1           milestone 1 on a tape of its own: the scroll engine
#   make run-m1       that one in FBZX
#   make check        the checks (planzx.md)
#   make clean

SHELL  := /bin/bash
RASM   ?= rasm
PYTHON ?= python3
FBZX   ?= fbzx
BUILD  := build

.PHONY: all run m1 run-m1 check release screenshots docs clean

all: $(BUILD)/runner.tap $(BUILD)/runner48.z80 $(BUILD)/runner128.z80

$(BUILD):
	mkdir -p $(BUILD)

# --- data made by the tools ----------------------------------------------------
src/data/gfx.asm: tools/zxgfx.py tools/zxart.py gfx/logo_cpc.png
	$(PYTHON) tools/zxgfx.py

src/data/chunks.asm: tools/mklevel.py tools/zxart.py $(wildcard levels/chunks/*)
	$(PYTHON) tools/mklevel.py

src/data/text.asm src/data/text_ids.asm &: tools/mktext.py tools/zxart.py text/en.txt text/el.txt
	$(PYTHON) tools/mktext.py

src/data/music.asm: tools/mkmusic.py $(wildcard music/*.txt)
	$(PYTHON) tools/mkmusic.py

src/data/gfx_menu.asm src/data/gfx_hud.asm: src/data/gfx.asm

# --- the game ------------------------------------------------------------------
GAME_SRC := $(wildcard src/*.asm) src/data/gfx.asm src/data/gfx_menu.asm src/data/gfx_hud.asm \
	src/data/chunks.asm src/data/text.asm src/data/text_ids.asm src/data/music.asm

GAME_BIN := $(BUILD)/runner.bin $(BUILD)/runner.sym

$(GAME_BIN) &: $(GAME_SRC) | $(BUILD)
	$(RASM) src/runner.asm -s -sa -os $(BUILD)/runner.sym

$(BUILD)/loading.scr: tools/zxloadscr.py gfx/loading_art.jpg tools/zxart.py gfx/logo_cpc.png | $(BUILD)
	$(PYTHON) tools/zxloadscr.py gfx/loading_art.jpg $@ --png $(BUILD)/loading.png

$(BUILD)/runner.tap: $(BUILD)/runner.bin $(BUILD)/runner.sym $(BUILD)/loading.scr src/loader.bas tools/mktap.py
	$(PYTHON) tools/mktap.py $@ --sym $(BUILD)/runner.sym --tzx $(BUILD)/runner.tzx \
		--basic src/loader.bas RUNNER --screen $(BUILD)/loading.scr APER \
		--code $(BUILD)/runner.bin RUNNER BIN_ORG

$(BUILD)/runner48.z80: $(BUILD)/runner.bin $(BUILD)/runner.sym $(BUILD)/loading.scr tools/mkz80.py
	$(PYTHON) tools/mkz80.py $(BUILD)/runner.bin $(BUILD)/runner.sym $(BUILD)/loading.scr $@ --model 48

$(BUILD)/runner128.z80: $(BUILD)/runner.bin $(BUILD)/runner.sym $(BUILD)/loading.scr tools/mkz80.py
	$(PYTHON) tools/mkz80.py $(BUILD)/runner.bin $(BUILD)/runner.sym $(BUILD)/loading.scr $@ --model 128

run: $(BUILD)/runner.tap
	$(FBZX) $<

# --- manuals and release -------------------------------------------------------
screenshots: $(GAME_BIN) $(BUILD)/loading.scr
	$(PYTHON) tools/screenshots.py $(BUILD)/runner.bin $(BUILD)/runner.sym docs/screenshots

docs: docs/manual_en.md docs/manual_el.md tools/mkdocs.py
	$(PYTHON) tools/mkdocs.py

RELEASE := $(BUILD)/runner.tap $(BUILD)/runner.tzx $(BUILD)/runner48.z80 $(BUILD)/runner128.z80

release: all
	rm -rf release
	mkdir -p release
	cp $(RELEASE) release/
	cp docs/manual_en.pdf docs/manual_el.pdf release/
	cd release && sha256sum * > SHA256SUMS
	ls -l release

# --- milestone 1: the scroll engine -------------------------------------------
$(BUILD)/m1.bin $(BUILD)/m1.sym &: src/m1.asm src/config.asm src/irq.asm src/video.asm | $(BUILD)
	$(RASM) src/m1.asm -s -sa -os $(BUILD)/m1.sym

$(BUILD)/m1.tap: $(BUILD)/m1.bin $(BUILD)/m1.sym src/loader_m.bas tools/mktap.py
	$(PYTHON) tools/mktap.py $@ --sym $(BUILD)/m1.sym \
		--basic src/loader_m.bas M1 --code $(BUILD)/m1.bin M1 CODE_ORG

m1: $(BUILD)/m1.tap

run-m1: $(BUILD)/m1.tap
	$(FBZX) $<

# --- checks --------------------------------------------------------------------
GAME := $(BUILD)/runner.bin $(BUILD)/runner.sym

check: $(BUILD)/m1.bin $(BUILD)/m1.sym $(GAME) $(BUILD)/runner.tap
	@for m in 48 128; do \
		echo "=== the tape through the real ROM, $$m K ==="; \
		$(PYTHON) tools/zxcheck.py $(BUILD)/runner.tap --sym $(BUILD)/runner.sym \
			--bin $(BUILD)/runner.bin --blocks 6 --model $$m; r=$$?; \
		if [ $$r = 2 ]; then echo "    skipped (no emulator or ROM)"; \
		elif [ $$r != 0 ]; then exit 1; fi; done
	@echo "=== the interpreter's timing against the data sheet ==="
	@$(PYTHON) tools/z80timing.py
	@echo "=== m1: the picture copied behind the beam, speeds 1-8 ==="
	@$(PYTHON) tools/beamcheck.py $(BUILD)/m1.bin $(BUILD)/m1.sym --m1
	@for s in 2 5 7; do \
		echo "=== the world on the screen against its rows, speed $$s ==="; \
		$(PYTHON) tools/worldcheck.py $(GAME) --frames 400 --speed $$s || exit 1; done
	@for s in 4 5 6 7; do \
		echo "=== the game behind the beam, speed $$s (48K) ==="; \
		$(PYTHON) tools/beamcheck.py $(GAME) --game --frames 1000 \
			--poke no_crash=1 --poke scroll_speed=$$s || exit 1; done
	@echo "=== the game behind the beam, speed 6 (128K) ==="
	@$(PYTHON) tools/beamcheck.py $(GAME) --game --frames 1000 --model 128 \
		--poke no_crash=1 --poke scroll_speed=6
	@echo "=== the world's jobs against their bounds, speed 6 ==="
	@$(PYTHON) tools/jobcheck.py $(GAME) --frames 1000 --poke no_crash=1 --poke scroll_speed=6

clean:
	rm -rf $(BUILD)
