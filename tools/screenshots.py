#!/usr/bin/env python3
"""The manuals' screenshots, from the game running on tools/zxrun.py.

    tools/screenshots.py build/runner.bin build/runner.sym docs/screenshots

Drives the game through its menus with keys, as a player would, and saves a
PNG of each screen. The loading screen is tools/zxloadscr.py's preview.
"""

import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from zxrun import Machine  # noqa: E402

MODE_PLAY, MODE_OVER = 0, 5


def key(m, name, wait=12):
    m.press(name, 4)
    m.run_frames(wait)


def shot(m, out, name):
    path = os.path.join(out, name)
    m.png(path)
    print("wrote %s" % path)


def menu_shots(binary, sym, out):
    m = Machine(binary, sym, menu=True)
    m.run_frames(40)
    shot(m, out, "02_menu.png")
    key(m, "A")                                 # CONTROLS
    key(m, "SPACE", 20)
    shot(m, out, "04_controls.png")
    key(m, "SPACE", 20)
    for _ in range(2):                          # STORY
        key(m, "A")
    key(m, "SPACE", 30)
    shot(m, out, "03_story.png")
    key(m, "SPACE", 20)
    key(m, "L", 20)                             # Greek
    shot(m, out, "06_menu_greek.png")
    key(m, "L", 20)
    for _ in range(3):                          # back to START
        key(m, "Q")
    return m


def countdown_shot(binary, sym, out):
    m = Machine(binary, sym, menu=True)
    m.run_frames(40)
    for _ in range(4):                          # DIFFICULTY: twice to HARD
        key(m, "A")
    key(m, "SPACE")
    key(m, "SPACE")
    for _ in range(4):
        key(m, "Q")
    key(m, "SPACE", 30)
    shot(m, out, "07_hard_countdown.png")


def game_shots(binary, sym, out):
    m = Machine(binary, sym, menu=True)
    m.run_frames(40)
    key(m, "SPACE", 10)
    m.poke("no_crash", 1)
    m.run_frames(400)
    shot(m, out, "08_running.png")
    # a power-up's name on the track: wait for one to be put in
    for _ in range(4000):
        m.run_frames(2)
        if 2 <= m.peek("label_item") <= 7 and m.peek("label_wait") == 0 \
                and m.peekw("cur_top_row") - m.peekw("label_at") < 14:
            m.run_frames(6)
            shot(m, out, "09_power_up.png")
            break
    m.run_frames(2000)
    shot(m, out, "10_further.png")
    m.poke("no_crash", 0)
    for _ in range(400):                        # no hands: to the end
        m.run_frames(50)
        if m.peek("game_mode") == MODE_OVER:
            break
    m.run_frames(30)
    shot(m, out, "11_game_over.png")
    for k in ("Q", "SPACE", "Q", "SPACE", "SPACE"):
        key(m, k)
    m.run_frames(20)
    key(m, "SPACE", 30)
    shot(m, out, "12_high_scores.png")


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    binary, sym, out = sys.argv[1:]
    os.makedirs(out, exist_ok=True)
    loading = os.path.join(os.path.dirname(binary), "loading.png")
    if os.path.exists(loading):
        shutil.copy(loading, os.path.join(out, "01_loading.png"))
        print("wrote %s" % os.path.join(out, "01_loading.png"))
    menu_shots(binary, sym, out)
    countdown_shot(binary, sym, out)
    game_shots(binary, sym, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
