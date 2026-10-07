#!/usr/bin/env python3
"""The Spectrum's art, as pictures of colour letters (planzx.md 2.3).

Every picture is a grid of letters, one a pixel:

    k b r m g c y w   black blue red magenta green cyan yellow white
    K B R M G C Y W   the same BRIGHT (K is black)

and tools/zxgfx.py turns each 8x8 cell into a byte a line and an attribute:
at most two colours a cell, and bright and not bright never together (black
goes with either). Which of the two is the paper is the picture's `paper`
preference (the first of its letters found in the cell), else the colour
with more pixels.

Sprites (the runner, the scenery, the items) are masked and drawn in ink
only:   . transparent   X ink   o a hole (masked, not drawn: the paper shows)
and carry the ink colour their cells take (None: the cells keep theirs).

Tiles are drawn here in code, a row of the world at a time; the sprites are
ASCII further down. tools/zxgfx.py --preview draws them all to a PNG.
"""

# ---------------------------------------------------------------------------
# A picture
# ---------------------------------------------------------------------------


class Img:
    def __init__(self, w, h, fill="k", paper="k"):
        self.w, self.h = w, h
        self.p = [[fill] * w for _ in range(h)]
        self.paper = paper              # paper preference, see above

    def px(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.p[y][x] = c

    def rect(self, x0, y0, x1, y1, c):
        """Filled, inclusive."""
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                self.px(x, y, c)

    def hline(self, x0, x1, y, c):
        self.rect(x0, y, x1, y, c)

    def vline(self, x, y0, y1, c):
        self.rect(x, y0, x, y1, c)

    def paste(self, rows, x0=0, y0=0, colours=None):
        """ASCII rows; '.' leaves the pixel, other letters through `colours`
        (a dict) or as they are."""
        for dy, row in enumerate(rows):
            for dx, ch in enumerate(row):
                if ch == ".":
                    continue
                self.px(x0 + dx, y0 + dy, colours.get(ch, ch) if colours else ch)

    def recolour(self, old, new, x0=0, y0=0, x1=None, y1=None):
        x1 = self.w - 1 if x1 is None else x1
        y1 = self.h - 1 if y1 is None else y1
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                if self.p[y][x] == old:
                    self.p[y][x] = new

    def mirrored(self):
        m = Img(self.w, self.h, paper=self.paper)
        m.p = [row[::-1] for row in self.p]
        return m

    def flipped(self):
        m = Img(self.w, self.h, paper=self.paper)
        m.p = [list(row) for row in self.p[::-1]]
        return m

    def copy(self):
        m = Img(self.w, self.h, paper=self.paper)
        m.p = [list(row) for row in self.p]
        return m

    def rows(self):
        return ["".join(r) for r in self.p]


class Sprite:
    """Masked: rows of . X o, an ink (letter or None)."""

    def __init__(self, rows, ink=None, width=None):
        w = width or max(len(r) for r in rows)
        w = (w + 7) // 8 * 8
        self.rows = [r.ljust(w, ".") for r in rows]
        self.w, self.h = w, len(rows)
        self.ink = ink

    def mirrored(self):
        return Sprite([r[::-1] for r in self.rows], self.ink, self.w)


def parse_sprites(text):
    """':name [ink]' then rows, as in the Loukoumas port's assets."""
    out, name, ink, rows = {}, None, None, []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(":"):
            if name:
                out[name] = Sprite(rows, ink)
            parts = s[1:].split()
            name, ink, rows = parts[0], (parts[1] if len(parts) > 1 else None), []
        elif s and not s.startswith("#"):
            rows.append(s)
    if name:
        out[name] = Sprite(rows, ink)
    return out


# ---------------------------------------------------------------------------
# The track: 32x8 lane tiles (assets.py TRACK_TILES order of the CPC)
# ---------------------------------------------------------------------------
TRAIN_TYPES = (1, 2, 3)
TRACK_TILES = (
    ["rail_a", "rail_b", "stop_0", "stop_1", "signal_0", "signal_1"]
    + [f"wagon{t}_{part}" for t in TRAIN_TYPES
       for part in ("end_bottom", "body_a", "body_b", "end_top", "coupler")]
    + [f"loco{t}_{part}" for t in TRAIN_TYPES for part in ("nose", "body", "pantograph", "nose_top")]
    + [f"ramp_up_{i}" for i in range(3)]
    + [f"ramp_down_{i}" for i in range(3)]
)

LANE = 32
RAIL_L = (5, 6)                 # the rails' pixels
RAIL_R = (25, 26)
TRAIN_X0, TRAIN_X1 = 2, 29      # a train's body (28 px, the CPC's 24 of 28)

# liveries: body paper, detail ink, window ink, edge ink (cells 0 and 3)
LIVERY = {
    1: dict(body="g", detail="k", window="k", stripe="w"),     # ISAP green
    2: dict(body="w", detail="b", window="b", stripe="b"),     # white and blue
    3: dict(body="r", detail="y", window="y", stripe="y"),     # red and orange
}


def rails(sleepers=(1, 5), phase=0):
    """Plain track: concrete sleepers (grey) between bright rails."""
    t = Img(LANE, 8, paper="k")
    for s in sleepers:
        t.rect(3, s, 28, s + 1, "w")
    # the sleepers' ends and the rails: bright, in the edge cells
    t.recolour("w", "W", 0, 0, 7, 7)
    t.recolour("w", "W", 24, 0, 31, 7)
    for x in RAIL_L + RAIL_R:
        t.vline(x, 0, 7, "W")
    if phase:                   # rail_b: a joint in the rails
        t.px(RAIL_L[0], 3, "k")
        t.px(RAIL_R[1], 3, "k")
    return t


def stop(k):
    """A buffer stop: a red-and-black beam across the lane, its base."""
    t = rails()
    t.recolour("W", "R", 0, 0, 7, 7)
    t.recolour("W", "R", 24, 0, 31, 7)
    t.recolour("w", "k")
    if k == 1:                              # the beam (the player meets it first? no: top row)
        t.rect(1, 2, 30, 6, "R")
        for x in range(3, 29, 6):
            t.rect(x, 3, x + 2, 5, "k")
        t.hline(1, 30, 2, "R")
    else:                                   # the base: two buffers, red
        t.rect(4, 0, 7, 3, "R")
        t.rect(24, 0, 27, 3, "R")
        t.hline(8, 23, 1, "W")
        t.recolour("W", "R", 8, 1, 23, 1)
    return t


def signal(k):
    """Always red on the Spectrum: a gantry with a lamp at each end (row 0),
    and the stop line under it (row 1)."""
    t = rails()
    if k == 0:
        t.recolour("W", "R", 0, 0, 7, 7)
        t.recolour("W", "R", 24, 0, 31, 7)
        t.rect(0, 1, 7, 6, "k")
        t.rect(24, 1, 31, 6, "k")
        for x0 in (1, 25):                  # the lamps: round, red
            t.paste([".RRRR.", "RRRRRR", "RRRRRR", "RRRRRR", ".RRRR."], x0, 1)
        t.rect(8, 1, 23, 6, "k")
        t.hline(8, 23, 3, "W")              # the beam between them
        t.hline(8, 23, 4, "W")
    else:
        t.hline(8, 23, 6, "W")              # the stop line, dashed
        for x in range(9, 23, 4):
            t.px(x, 6, "k")
        t.recolour("w", "W")
    return t


def body_base(liv, ends=True):
    """A train's lane: dark margins, the body in the livery's paper."""
    L = LIVERY[liv]
    t = Img(LANE, 8, fill=L["body"], paper=L["body"])
    for x in (0, 1, 30, 31):
        t.vline(x, 0, 7, "k")
    return t


def edge_cells(t, liv):
    """A train's outer cells (0 and 3) hold its body colour and black only:
    whatever else was drawn there is black."""
    body = LIVERY[liv]["body"]
    for y in range(8):
        for x in list(range(8)) + list(range(24, 32)):
            if t.p[y][x] not in (body, "k"):
                t.p[y][x] = "k"
    return t


def wagon(liv, part):
    L = LIVERY[liv]
    t = body_base(liv)
    d = L["detail"]
    # the roof's edges, in the detail colour, inside cells 0 and 3
    if part in ("body_a", "body_b"):
        t.vline(3, 0, 7, d)
        t.vline(28, 0, 7, d)
        if part == "body_a":                # roof vents
            t.rect(11, 2, 14, 5, d)
            t.rect(17, 2, 20, 5, d)
            t.rect(12, 3, 13, 4, L["body"])
            t.rect(18, 3, 19, 4, L["body"])
        else:
            t.hline(9, 22, 4, d)
    elif part == "end_bottom":              # the end the runner meets
        t.vline(3, 0, 5, d)
        t.vline(28, 0, 5, d)
        t.rect(2, 7, 29, 7, d)
        t.px(2, 6, "k")
        t.px(29, 6, "k")
        t.hline(4, 27, 5, d)
    elif part == "end_top":
        t.vline(3, 2, 7, d)
        t.vline(28, 2, 7, d)
        t.rect(2, 0, 29, 0, d)
        t.px(2, 1, "k")
        t.px(29, 1, "k")
        t.hline(4, 27, 2, d)
    elif part == "coupler":                 # the gap between two wagons
        t = rails()
        t.rect(0, 0, 31, 7, "k")
        t.rect(13, 0, 18, 7, "w")
        t.rect(14, 0, 17, 7, "k")
        t.rect(15, 2, 16, 5, "w")
        return t
    return edge_cells(t, liv)


def loco(liv, part):
    L = LIVERY[liv]
    t = body_base(liv)
    d, w = L["detail"], L["window"]
    if part == "nose":                      # the cab facing the runner
        t.vline(3, 0, 3, d)
        t.vline(28, 0, 3, d)
        t.rect(5, 3, 26, 5, w)              # the windscreen
        t.rect(15, 3, 16, 5, L["body"])
        t.hline(2, 29, 7, d)
        t.px(2, 6, "k")
        t.px(29, 6, "k")
        t.px(3, 7, "k")
    elif part == "nose_top":                # the far cab, facing away
        t.vline(3, 4, 7, d)
        t.vline(28, 4, 7, d)
        t.rect(5, 2, 26, 4, w)
        t.rect(15, 2, 16, 4, L["body"])
        t.hline(2, 29, 0, d)
        t.px(2, 1, "k")
        t.px(29, 1, "k")
    elif part == "body":
        t.vline(3, 0, 7, d)
        t.vline(28, 0, 7, d)
        t.rect(8, 1, 23, 6, d)              # the machinery hatch
        t.rect(9, 2, 22, 5, L["body"])
        for x in range(10, 22, 3):
            t.vline(x, 2, 5, d)
    elif part == "pantograph":
        t.vline(3, 0, 7, d)
        t.vline(28, 0, 7, d)
        t.hline(6, 25, 3, d)                # the bow
        t.hline(6, 25, 4, d)
        t.paste(["d......d", ".d....d.", "..d..d..", "...dd..."], 12, 0, {"d": d})
    return edge_cells(t, liv)


def ramp(up, k):
    """Concrete ramps onto a train's roof: grey, with yellow chevrons; row k
    of 3 counted from the bottom (k=0 meets the runner first going up)."""
    t = Img(LANE, 8, fill="w", paper="w")
    for x in (0, 1, 30, 31):
        t.vline(x, 0, 7, "k")
    for y in range(8):                      # the side walls
        t.px(2, y, "k")
        t.px(29, y, "k")
    # chevrons: steeper as it climbs; on a ramp down they point the other way
    for i in range(0, 8, 4):
        y = i + 1
        for dx in range(10):
            yy = y + dx // 3 if up else y + 2 - dx // 3
            t.px(15 - dx, yy % 8, "k")
            t.px(16 + dx, yy % 8, "k")
    # the strip at the low end: k=0 of a ramp up, k=0 of a ramp down
    # (which is its top row, next to the roof): dark
    if k == 0 and up:
        t.hline(2, 29, 7, "k")
    if k == 2 and not up:
        t.hline(2, 29, 0, "k")
    return t


def track_tile(name):
    if name in ("rail_a", "rail_b"):
        return rails(phase=name == "rail_b")
    if name.startswith("stop_"):
        return stop(int(name[-1]))
    if name.startswith("signal_"):
        return signal(int(name[-1]))
    if name.startswith("wagon"):
        return wagon(int(name[5]), name.split("_", 1)[1])
    if name.startswith("loco"):
        return loco(int(name[4]), name.split("_", 1)[1])
    kind, k = name.rsplit("_", 1)
    return ramp(kind == "ramp_up", int(k))


def track_tiles():
    return {n: track_tile(n) for n in TRACK_TILES}


# ---------------------------------------------------------------------------
# The sides: 48x8, the left one (the right is its mirror). Byte 0 is the
# outer edge, byte 5 is next to the track.
# ---------------------------------------------------------------------------
SIDE = 48
URBAN_TILES = ["road_a", "road_b", "road_cross_0", "road_cross_1", "road_kiosk_0", "road_kiosk_1"]
FOREST_TILES = (["ground_a", "ground_b", "path", "fence"]
                + [f"trans_urban_forest_{i}" for i in range(2)]
                + [f"trans_forest_urban_{i}" for i in range(2)])
# The avenue's three lanes are bytes 0-1, 2-3 and 4-5 (a car is 12 px wide
# in the middle of its 16); the kerb runs down byte 5's last pixels.
KERB_X = (46, 47)
LANE_LINES = (15, 31)           # the dashed lines between the avenue's lanes


def road(dash):
    t = Img(SIDE, 8, paper="k")
    for x in KERB_X:
        t.vline(x, 0, 7, "w")
    if dash:                    # dashes 8 lines on, 8 off: road_a / road_b
        for x in LANE_LINES:
            t.vline(x, 1, 6, "w")
    t.px(44, 2, "w")            # grit on the asphalt by the kerb
    t.px(43, 6, "w")
    return t


def crossing(k):
    t = road(False)
    for x in range(1, 44, 6):   # zebra stripes, two rows of them
        t.rect(x, 1 if k == 0 else 0, x + 3, 7 if k == 0 else 6, "W")
    t.recolour("w", "W")
    return t


def kiosk(k):
    """The periptero in the outer lane (bytes 0-1), two rows: k=0 the
    bottom row (its counter), k=1 the top (its roof)."""
    t = road(k == 0)
    t.rect(0, 0, 15, 7, "k")
    if k == 1:
        t.rect(1, 1, 14, 7, "y")            # the roof, an awning on all sides
        t.hline(1, 14, 1, "k")
        for x in range(2, 14, 3):
            t.vline(x, 2, 7, "k")
    else:
        t.rect(1, 0, 14, 5, "y")
        t.rect(3, 1, 12, 4, "k")            # the newspapers on the counter
        t.hline(4, 11, 2, "y")
        t.hline(1, 14, 6, "k")
    t.paper = "k"
    return t


def ground(phase):
    t = Img(SIDE, 8, fill="g", paper="g")
    import random
    rnd = random.Random(7 + phase)
    for _ in range(14):         # tufts of grass, dark
        x, y = rnd.randrange(1, 46), rnd.randrange(0, 7)
        t.px(x, y, "k")
        t.px(x + 1, y + 1, "k")
    t.vline(47, 0, 7, "k")      # the ditch by the track
    return t


def path():
    t = ground(0)
    t.rect(0, 0, 46, 7, "y")    # a dirt path across
    for x in range(6, 40, 7):
        t.px(x, 3, "k")
    return t


def fence():
    t = ground(1)
    t.rect(0, 0, 47, 7, "g")
    t.vline(47, 0, 7, "k")
    t.hline(0, 46, 2, "k")      # two rails and the posts
    t.hline(0, 46, 5, "k")
    for x in range(3, 46, 8):
        t.rect(x, 1, x + 1, 6, "k")
    return t


def transition(to_forest, k):
    """Two rows from one to the other. k=0 is the bottom row."""
    lower, upper = (road(True), ground(0)) if to_forest else (ground(0), road(True))
    t = (lower if k == 0 else upper).copy()
    # a hedge where they meet: on the top line of the bottom row
    # and the bottom line of the top row
    y = 0 if k == 0 else 7
    t.rect(0, y, 47, y, "k")
    return t


def side_tile(name):
    if name in ("road_a", "road_b"):
        return road(name == "road_a")
    if name.startswith("road_cross_"):
        return crossing(int(name[-1]))
    if name.startswith("road_kiosk_"):
        return kiosk(int(name[-1]))
    if name in ("ground_a", "ground_b"):
        return ground(name == "ground_b")
    if name == "path":
        return path()
    if name == "fence":
        return fence()
    to_forest = name.startswith("trans_urban")
    return transition(to_forest, int(name[-1]))


def side_tiles(names):
    """name and name_m (mirrored, for the right side), in pairs as on the CPC."""
    out = {}
    for n in names:
        t = side_tile(n)
        out[n] = t
        out[n + "_m"] = t.mirrored()
    return out


# ---------------------------------------------------------------------------
# Bridges: whole rows of the playfield, 192x8. Bottom to top: the shadow
# row, then the deck rows (src/world.asm footbridge_rows / roadbridge_rows).
# ---------------------------------------------------------------------------
BRIDGE_ROWS = ([f"footbridge_{i}" for i in range(3)] + ["footbridge_shadow"]
               + [f"roadbridge_{i}" for i in range(6)] + ["roadbridge_shadow"])
PLAYFIELD = 192


def footbridge(k):
    """A steel footbridge: k=0 its bottom railing, 1 the walkway, 2 the top
    railing. Red girders, a grey deck."""
    t = Img(PLAYFIELD, 8, fill="w", paper="w")
    if k in (0, 2):
        t.rect(0, 0, 191, 7, "r")
        t.paper = "r"
        y = 6 if k == 0 else 1          # the railing's top bar, outside
        t.hline(0, 191, y, "k")
        for x in range(2, 192, 6):      # the lattice
            t.vline(x, 2 if k == 0 else 1, 6 if k == 0 else 5, "k")
        t.hline(0, 191, 7 if k == 0 else 0, "k")
    else:
        for x in range(0, 192, 12):     # deck plates
            t.vline(x, 0, 7, "k")
        t.hline(0, 191, 0, "k")
        t.hline(0, 191, 7, "k")
    return t


def roadbridge(k):
    """A concrete road bridge: k=0 and 5 its walls, 1-4 the carriageway
    (two lanes each way, a white line in the middle)."""
    t = Img(PLAYFIELD, 8, fill="k", paper="k")
    if k in (0, 5):
        t.rect(0, 0, 191, 7, "w")
        t.paper = "w"
        t.hline(0, 191, 0 if k == 5 else 7, "k")
        for x in range(4, 192, 16):
            t.rect(x, 2, x + 7, 5, "k")
            t.rect(x + 1, 3, x + 6, 4, "w")
    else:
        if k in (2, 3):
            y = 7 if k == 2 else 0      # the middle line, between rows 2 and 3
            t.hline(0, 191, y, "W")
            t.paper = "k"
        y = 3
        for x in range(4, 192, 16):     # lane dashes
            t.hline(x, x + 7, y, "W")
    return t


def bridge_shadow():
    t = Img(PLAYFIELD, 8, fill="k", paper="k")
    for y in range(8):                  # a dithered edge: blue on black
        for x in range((y & 1), 192, 2):
            if y < 3:
                t.px(x, y, "b")
    return t


def bridge_row(name):
    if name.endswith("shadow"):
        return bridge_shadow()
    k = int(name[-1])
    return footbridge(k) if name.startswith("foot") else roadbridge(k)


def bridge_rows():
    return {n: bridge_row(n) for n in BRIDGE_ROWS}


# ---------------------------------------------------------------------------
# Station platforms: the inner 3 bytes of a side (24x8), over the avenue or
# the forest. PLATFORM_KINDS / PLATFORM_SEQ as the CPC's tools/assets.py.
# ---------------------------------------------------------------------------
PLATFORM_SEQ = [None, "end_hi", "plain", "bench", "plain", "plain", "bench", "plain",
                "roof", "sign", "roof", "roof", "sign", "roof", "roof_lo",
                "plain", "bench", "plain", "end_lo", None, None, None, None]
PLATFORM_KINDS = ["end_lo", "end_hi", "plain", "bench", "sign", "roof", "roof_lo"]
PLAT_W = 24


def platform(kind):
    """The left side's platform: byte 0 meets the avenue, byte 2 the track."""
    t = Img(PLAT_W, 8, fill="w", paper="w")
    t.vline(23, 0, 7, "k")              # the platform edge, dark
    t.vline(21, 0, 7, "k")
    if kind == "end_lo":                # the ramp down at the far end... the
        t.rect(0, 5, 23, 7, "k")        # near end, k: concrete on top
        for x in range(0, 22, 3):
            t.px(x, 4, "k")
    elif kind == "end_hi":
        t.rect(0, 0, 23, 2, "k")
        for x in range(0, 22, 3):
            t.px(x, 3, "k")
    elif kind == "plain":
        t.hline(0, 20, 4, "k")
        t.px(0, 4, "w")
    elif kind == "bench":
        t.rect(4, 2, 15, 3, "k")        # the seat and its back
        t.hline(4, 15, 5, "k")
        t.px(5, 4, "k")
        t.px(14, 4, "k")
    elif kind in ("roof", "roof_lo"):
        t.rect(0, 0, 20, 7, "r")        # the red canopy, ribbed
        t.paper = "r"
        for y in range(1, 8, 2):
            t.hline(0, 20, y, "k")
        if kind == "roof_lo":
            t.hline(0, 20, 7, "k")
    elif kind == "sign":
        t.rect(0, 0, 20, 7, "r")
        t.rect(0, 0, 15, 7, "B")        # the name board, blue and white
        t.paper = "rB"
        for x in range(2, 14, 3):
            t.rect(x, 3, x + 1, 4, "W")
        t.rect(16, 1, 20, 6, "k")
    if kind in ("roof", "roof_lo", "sign"):
        t.recolour("w", "r", 16, 0, 23, 7)  # the canopy reaches the edge
    return t


def platform_tiles():
    out = {}
    for k in PLATFORM_KINDS:
        t = platform(k)
        out[k] = t
        out[k + "_m"] = t.mirrored()
    return out


# ---------------------------------------------------------------------------
# The runner, seen from behind: five sizes (one a height level, plan.md 1.2
# of the CPC: +2 px wide and +2 lines a level), drawn from the same parts so
# they look alike. Drawn in the ink of the cells it stands in; the mask's
# outline keeps it apart from them.
# ---------------------------------------------------------------------------
RUNNER_FRAMES = (
    [("s1_" + f, 1) for f in ("run0", "run1", "run2", "run3", "lean_l", "lean_r", "crash0", "crash1")]
    + [("s2_" + f, 2) for f in ("jump_up", "jump_down")]
    + [("s3_" + f, 3) for f in ("run0", "run1", "run2", "run3", "lean_l", "lean_r",
                                 "crash0", "crash1", "jump_up", "jump_down")]
    + [("s4_" + f, 4) for f in ("jump_up", "jump_down")]
    + [("s5_jump", 5)]
)


def runner(size, pose):
    W, H = 10 + 2 * size, 14 + 2 * size
    canvas = 16 if W <= 16 else 32
    g = [["."] * canvas for _ in range(H)]
    cx = canvas // 2                    # the centre line falls between two pixels

    def span(y, half, c="X", shift=0):
        if 0 <= y < H:
            for x in range(cx - half + shift, cx + half + shift):
                if 0 <= x < canvas:
                    g[y][x] = c

    def put(x, y, c="X"):
        if 0 <= y < H and 0 <= x < canvas:
            g[y][x] = c

    hh = 4 + (size >= 2) + (size >= 4)          # head
    th = 5 + (size + 1) // 2                    # torso
    lh = H - hh - 1 - th - 1                    # legs
    lean = {"lean_l": -1, "lean_r": 1}.get(pose, 0)
    hw = 2 + (size >= 3)                        # half widths: head, torso
    tw = 2 + (size + 1) // 2
    y = 0
    for i in range(hh):                         # the head: hair, rounded
        w = hw - (1 if i in (0, hh - 1) else 0)
        span(y + i, w, shift=lean * 2)
    put(cx - 1 + 2 * lean, hh - 2, "o")         # the nape
    put(cx + 2 * lean, hh - 2, "o")
    y += hh
    span(y, 1, shift=lean)                      # the neck
    y += 1
    torso_top = y
    for i in range(th):                         # shoulders, then the shirt narrowing
        span(y + i, tw - (1 if i >= th - 2 else 0), shift=lean)
    put(cx - 1 + lean, torso_top + 2, "o")      # a fold down the back
    put(cx + lean, torso_top + 3, "o")
    y += th
    span(y, tw - 1, "o")                        # the belt
    y += 1
    legs_top = y
    # arms: by the sides of the shirt, a pixel apart from it, swinging
    left_arm, right_arm = {"run0": (0, 2), "run1": (1, 1), "run2": (2, 0), "run3": (1, 1)}.get(pose, (1, 1))
    ax_l, ax_r = cx - tw - 3 + lean, cx + tw + 1 + lean
    for yy in range(torso_top, torso_top + 2):  # the shoulders reach the arms
        put(ax_l + 1, yy)
        put(ax_l + 2, yy)
        put(ax_r, yy)
        put(ax_r - 1, yy)
    if pose.startswith("crash") or pose == "jump_up":
        up_l = 0 if pose != "crash1" else 2
        up_r = 2 if pose == "crash0" else 0
        for i in range(hh + 1):
            put(ax_l, torso_top - i + up_l)
            put(ax_l + 1, torso_top - i + up_l)
            put(ax_r, torso_top - i + up_r)
            put(ax_r + 1, torso_top - i + up_r)
    elif pose in ("jump_down", "jump"):
        for i in range(3):                      # arms out, wide
            put(ax_l - i, torso_top + 1 + i // 2)
            put(ax_l - i, torso_top + 2 + i // 2)
            put(ax_r + 1 + i, torso_top + 1 + i // 2)
            put(ax_r + 1 + i, torso_top + 2 + i // 2)
    else:
        for i in range(th - 2 + left_arm):
            put(ax_l, torso_top + 1 + i)
            put(ax_l + 1, torso_top + 1 + i)
            put(ax_l + 2, torso_top + 1 + i, "o")
        for i in range(th - 2 + right_arm):
            put(ax_r, torso_top + 1 + i)
            put(ax_r + 1, torso_top + 1 + i)
            put(ax_r - 1, torso_top + 1 + i, "o")
    # legs
    lw = 2 + (size >= 3)
    gap = 1 + (size >= 4)
    l_len, r_len = {"run0": (lh, lh - 2), "run1": (lh - 1, lh - 1), "run2": (lh - 2, lh),
                    "run3": (lh - 1, lh - 1)}.get(pose, (lh, lh))
    spread = 0
    if pose == "jump_up":
        l_len = r_len = lh - 2                  # tucked
    if pose in ("jump_down", "jump", "crash0", "crash1"):
        spread = 1
    for i in range(l_len):
        for k in range(lw):
            put(cx - gap // 2 - lw + k - spread * (i // 2), legs_top + i)
    for i in range(r_len):
        for k in range(lw):
            put(cx + (gap + 1) // 2 + k + spread * (i // 2), legs_top + i)
    return Sprite(["".join(r) for r in g])


def runner_sprites():
    return {name: runner(size, name.split("_", 1)[1]) for name, size in RUNNER_FRAMES}


# shadows on the ground (sh2) and on a roof (sh3): dithered holes
def shadow(w, h):
    rows = []
    for y in range(h):
        r = ""
        for x in range(16):
            dx, dy = (x - 7.5) / (w / 2), (y - (h - 1) / 2) / (h / 2)
            r += "o" if dx * dx + dy * dy <= 1 and (x + y) & 1 else "."
        rows.append(r)
    return Sprite(rows)


def shadow_sprites():
    return {"sh2": shadow(12, 4), "sh3": shadow(14, 6)}


# ---------------------------------------------------------------------------
# Items: the coin (in the lane: 16 wide, the coin 12; four turns for the
# ones that fly to the runner) and the six power-ups, badges 16x12.
# ---------------------------------------------------------------------------
ITEMS_ART = """
:coin0 Y
...XXXXXXXXXX...
..XXXooooooXXX..
..XXoXXXXXXoXX..
..XXoXXooXXoXX..
..XXoXXooXXoXX..
..XXoXXXXXXoXX..
..XXXooooooXXX..
...XXXXXXXXXX...
:coin1 Y
.....XXXXXX.....
....XXooooXX....
....XoXXXXoX....
....XoXooXoX....
....XoXooXoX....
....XoXXXXoX....
....XXooooXX....
.....XXXXXX.....
:coin2 Y
.......XX.......
.......XX.......
.......XX.......
.......XX.......
.......XX.......
.......XX.......
.......XX.......
.......XX.......
:coin3 Y
.....XXXXXX.....
....XXooooXX....
....XoXXXXoX....
....XoXXoXoX....
....XoXXoXoX....
....XoXXXXoX....
....XXooooXX....
.....XXXXXX.....
:pu_magnet R
...XXXXXXXXXX...
..XXooooooooXX..
.XXoXXXooXXXoXX.
.XXoXXXooXXXoXX.
.XXoXXooooXXoXX.
.XXoXXooooXXoXX.
.XXoXXooooXXoXX.
.XXoXXooooXXoXX.
.XXoXooooooXoXX.
.XXooooooooooXX.
..XXooooooooXX..
...XXXXXXXXXX...
:pu_turbo Y
...XXXXXXXXXX...
..XXooooooooXX..
.XXoooXXoooooXX.
.XXooooXXooooXX.
.XXoooooXXoooXX.
.XXooooooXXooXX.
.XXoooooXXoooXX.
.XXooooXXooooXX.
.XXoooXXoooooXX.
.XXooooooooooXX.
..XXooooooooXX..
...XXXXXXXXXX...
:pu_slow G
...XXXXXXXXXX...
..XXooooooooXX..
.XXooooooooooXX.
.XXooXXXXXooXXX.
.XXoXXoXoXXoXoX.
.XXoXoXoXoXXXoX.
.XXoXXXXXXXooXX.
.XXooXooooXooXX.
.XXooooooooooXX.
.XXooooooooooXX.
..XXooooooooXX..
...XXXXXXXXXX...
:pu_spring C
...XXXXXXXXXX...
..XXooooooooXX..
.XXoooXXXXoooXX.
.XXooooooXoooXX.
.XXoooXXXXoooXX.
.XXoooXooooooXX.
.XXoooXXXXoooXX.
.XXooooooXoooXX.
.XXoooXXXXoooXX.
.XXooooooooooXX.
..XXooooooooXX..
...XXXXXXXXXX...
:pu_helmet W
...XXXXXXXXXX...
..XXooooooooXX..
.XXooooooooooXX.
.XXoooXXXXoooXX.
.XXooXXXXXXooXX.
.XXoXXXoXXXXoXX.
.XXoXXXoXXXXoXX.
.XXoXXXXXXXXoXX.
.XXXXXXXXXXXXXX.
.XXooooooooooXX.
..XXooooooooXX..
...XXXXXXXXXX...
:pu_ticket M
...XXXXXXXXXX...
..XXooooooooXX..
.XXooooooooooXX.
.XXoXXXXXXXXoXX.
.XXoXoXoXooXoXX.
.XXoXXoXXoXXoXX.
.XXoXoXoXooXoXX.
.XXoXXXXXXXXoXX.
.XXooooooooooXX.
.XXooooooooooXX.
..XXooooooooXX..
...XXXXXXXXXX...
"""


def item_sprites():
    return parse_sprites(ITEMS_ART)


# ---------------------------------------------------------------------------
# Scenery: the avenue's traffic (top down, going up the screen; the right
# side's are mirrored) and the forest's trees, bushes and rocks.
# ---------------------------------------------------------------------------
SCENERY_ART = """
:car_red R
...XXXXXXXXXX...
..XXXXXXXXXXXX..
..XXooooooooXX..
..XXoXXXXXXoXX..
..XXXXXXXXXXXX..
..XXXXXXXXXXXX..
..XXXXXXXXXXXX..
..XXXXXXXXXXXX..
..XXoXXXXXXoXX..
..XXooooooooXX..
..XXoXXXXXXoXX..
..XXXXXXXXXXXX..
..XXXXXXXXXXXX..
..XoXXXXXXXXoX..
..XXXXXXXXXXXX..
...XXXXXXXXXX...
:car_blue B
...XXXXXXXXXX...
..XXXXXXXXXXXX..
..XXXXXXXXXXXX..
..XXooooooooXX..
..XXoXXXXXXoXX..
..XXXXXXXXXXXX..
..XXXXXXXXXXXX..
..XXXXXXXXXXXX..
..XXXXXXXXXXXX..
..XXoXXXXXXoXX..
..XXooooooooXX..
..XXXXXXXXXXXX..
..XXXXXXXXXXXX..
..XoXXXXXXXXoX..
..XXXXXXXXXXXX..
...XXXXXXXXXX...
:car_white W
...XXXXXXXXXX...
..XXXXXXXXXXXX..
..XXooooooooXX..
..XXoXXXXXXoXX..
..XXXXXXXXXXXX..
..XXXXXXooXXXX..
..XXXXXXooXXXX..
..XXXXXXXXXXXX..
..XXoXXXXXXoXX..
..XXooooooooXX..
..XXXXXXXXXXXX..
..XXXXXXXXXXXX..
..XXXXXXXXXXXX..
..XoXXXXXXXXoX..
..XXXXXXXXXXXX..
...XXXXXXXXXX...
:taxi Y
...XXXXXXXXXX...
..XXXXXXXXXXXX..
..XXooooooooXX..
..XXoXXXXXXoXX..
..XXXXXooXXXXX..
..XXXXooooXXXX..
..XXXXXooXXXXX..
..XXXXXXXXXXXX..
..XXoXXXXXXoXX..
..XXooooooooXX..
..XXXXXXXXXXXX..
..XXXXXXXXXXXX..
..XXXXXXXXXXXX..
..XoXXXXXXXXoX..
..XXXXXXXXXXXX..
...XXXXXXXXXX...
:bus C
..XXXXXXXXXXXX..
..XXooooooooXX..
..XXoXXXXXXoXX..
..XXXXXXXXXXXX..
..XXoXXXXXXoXX..
..XXXXXXXXXXXX..
..XXXXXXXXXXXX..
..XXoXXXXXXoXX..
..XXXXXXXXXXXX..
..XXXXXXXXXXXX..
..XXoXXXXXXoXX..
..XXXXXXXXXXXX..
..XXXXXXXXXXXX..
..XXoXXXXXXoXX..
..XXXXXXXXXXXX..
..XXXXXXXXXXXX..
..XXoXXXXXXoXX..
..XXXXXXXXXXXX..
..XXXXXXXXXXXX..
..XXoXXXXXXoXX..
..XXXXXXXXXXXX..
..XXXXXXXXXXXX..
..XXoXXXXXXoXX..
..XXXXXXXXXXXX..
..XXXXXXXXXXXX..
..XXoXXXXXXoXX..
..XXXXXXXXXXXX..
..XXooooooooXX..
..XXoXXXXXXoXX..
..XXXXXXXXXXXX..
..XoXXXXXXXXoX..
..XXXXXXXXXXXX..
:trolley Y
.....X....X.....
.....X....X.....
......X..X......
..XXXXXXXXXXXX..
..XXooooooooXX..
..XXoXXXXXXoXX..
..XXXXXXXXXXXX..
..XXoXXXXXXoXX..
..XXXXXXXXXXXX..
..XXXXooXXXXXX..
..XXXXooXXXXXX..
..XXoXXXXXXoXX..
..XXXXXXXXXXXX..
..XXXXXXXXXXXX..
..XXoXXXXXXoXX..
..XXXXXXXXXXXX..
..XXXXXXXXXXXX..
..XXoXXXXXXoXX..
..XXXXXXXXXXXX..
..XXXXooXXXXXX..
..XXXXooXXXXXX..
..XXoXXXXXXoXX..
..XXXXXXXXXXXX..
..XXXXXXXXXXXX..
..XXoXXXXXXoXX..
..XXXXXXXXXXXX..
..XXXXXXXXXXXX..
..XXooooooooXX..
..XXoXXXXXXoXX..
..XXXXXXXXXXXX..
..XoXXXXXXXXoX..
..XXXXXXXXXXXX..
:pine k
...........XX...........
..........XXXX..........
.........XXoXXX.........
........XXXXXoXX........
.......XXoXXXXXXX.......
......XXXXXXoXXXXX......
.......XXXXXXXXoX.......
......XXoXXXXXXXXX......
.....XXXXXXoXXXXXXX.....
....XXXXoXXXXXXoXXXX....
.....XXXXXXXXXXXXXX.....
....XXXoXXXXXoXXXXXXX...
...XXXXXXXXXXXXXXoXXXX..
..XXXXoXXXXXoXXXXXXXXXX.
...XXXXXXXXXXXXXXXXXXX..
..XXXXXXXXoXXXXXXoXXXXX.
.XXXoXXXXXXXXXXXXXXXXXXX
..XXXXXXXXXXXXXXXXXXXXX.
....XXXXXXXXXXXXXXXXX...
.......XXXXXXXXXXX......
..........XXXX..........
..........XooX..........
..........XooX..........
...........XX...........
:oak k
.........XXXXXXXXXXXX...........
......XXXXXXXXXXXXXXXXXX........
....XXXXXXoXXXXXXXXoXXXXXX......
...XXXXoXXXXXXXXoXXXXXXXXXX.....
..XXXXXXXXXXXoXXXXXXXXoXXXXX....
.XXXoXXXXXXXXXXXXXXXXXXXXXXXX...
.XXXXXXXXXoXXXXXXXXoXXXXXXXXXX..
XXXXXXXXXXXXXXXXXXXXXXXXXoXXXX..
XXXXXoXXXXXXXXXoXXXXXXXXXXXXXXX.
XXXXXXXXXXXXXXXXXXXXXXoXXXXXXXX.
.XXXXXXXXXXoXXXXXXXXXXXXXXXXXXX.
.XXXoXXXXXXXXXXXXXXoXXXXXXXXXXX.
XXXXXXXXXXXXXXXXXXXXXXXXXXXoXXXX
XXXXXXXXXoXXXXXXXXXXXXXXXXXXXXXX
.XXXXXXXXXXXXXXXXoXXXXXXXXXXXXX.
.XXXXoXXXXXXXXXXXXXXXXXXXXoXXXX.
..XXXXXXXXXXXXXXXXXXXXXXXXXXXX..
...XXXXXXXXXoXXXXXXXXXoXXXXXX...
....XXXXXXXXXXXXXXXXXXXXXXXX....
......XXXXXXXXXXXXXXXXXXXX......
.........XXXXXXXXXXXXXX.........
.............XXXXXX.............
.............XooooX.............
..............XXXX..............
:cypress k
......XXXX......
.....XXXXXX.....
.....XXoXXX.....
....XXXXXoXX....
....XXoXXXXX....
....XXXXXXXX....
....XXXXoXXX....
....XoXXXXXX....
....XXXXXXoX....
....XXXoXXXX....
....XXXXXXXX....
....XXXXXoXX....
....XoXXXXXX....
....XXXXXXXX....
....XXXoXXXX....
....XXXXXXXX....
.....XXXXXX.....
.....XXXXXX.....
......XXXX......
.......XX.......
.......XX.......
.......XX.......
................
................
:bush k
................
....XXXXXXX.....
..XXXoXXXXXXX...
.XXXXXXXoXXXXX..
.XXoXXXXXXXXXX..
..XXXXXXoXXXX...
....XXXXXXX.....
................
:rock w
................
.....XXXXX......
...XXXXXXXXX....
..XXXXXoXXXXX...
..XXXXXXXXooXX..
...XXXXXXXXXX...
.....XXXXXX.....
................
"""
CARS = ["car_red", "car_blue", "car_white", "taxi", "bus", "trolley"]
TREES = ["pine", "oak", "cypress", "bush", "rock"]


def scenery_sprites():
    return parse_sprites(SCENERY_ART)


# ---------------------------------------------------------------------------
# The font: the CPC's glyphs (its font sheet, 5x7 in 6x8), a Spectrum cell
# each: one pixel in from the left and made bold (each line ORed with itself
# a pixel to the right), so 6x7 with two blank columns between letters.
# The characters a glyph draws: Latin capitals and the Greek ones of the
# same shape, digits, the rest of the Greek capitals, signs and arrows.
# ---------------------------------------------------------------------------
FONT_ART = [                           # (name, characters, 5x7 rows)
    ('space', ' ', '..... ..... ..... ..... ..... ..... .....'),
    ('a', 'AΑ', '.XXX. X...X X...X XXXXX X...X X...X X...X'),
    ('b', 'BΒ', 'XXXX. X...X X...X XXXX. X...X X...X XXXX.'),
    ('c', 'C', '.XXX. X...X X.... X.... X.... X...X .XXX.'),
    ('d', 'D', 'XXXX. X...X X...X X...X X...X X...X XXXX.'),
    ('e', 'EΕ', 'XXXXX X.... X.... XXXX. X.... X.... XXXXX'),
    ('f', 'F', 'XXXXX X.... X.... XXXX. X.... X.... X....'),
    ('g', 'G', '.XXX. X...X X.... X.XXX X...X X...X .XXXX'),
    ('h', 'HΗ', 'X...X X...X X...X XXXXX X...X X...X X...X'),
    ('i', 'IΙ', '.XXX. ..X.. ..X.. ..X.. ..X.. ..X.. .XXX.'),
    ('j', 'J', '..XXX ...X. ...X. ...X. ...X. X..X. .XX..'),
    ('k', 'KΚ', 'X...X X..X. X.X.. XX... X.X.. X..X. X...X'),
    ('l', 'L', 'X.... X.... X.... X.... X.... X.... XXXXX'),
    ('m', 'MΜ', 'X...X XX.XX X.X.X X.X.X X...X X...X X...X'),
    ('n', 'NΝ', 'X...X XX..X X.X.X X..XX X...X X...X X...X'),
    ('o', 'OΟ', '.XXX. X...X X...X X...X X...X X...X .XXX.'),
    ('p', 'PΡ', 'XXXX. X...X X...X XXXX. X.... X.... X....'),
    ('q', 'Q', '.XXX. X...X X...X X...X X.X.X X..X. .XX.X'),
    ('r', 'R', 'XXXX. X...X X...X XXXX. X.X.. X..X. X...X'),
    ('s', 'S', '.XXXX X.... X.... .XXX. ....X ....X XXXX.'),
    ('t', 'TΤ', 'XXXXX ..X.. ..X.. ..X.. ..X.. ..X.. ..X..'),
    ('u', 'U', 'X...X X...X X...X X...X X...X X...X .XXX.'),
    ('v', 'V', 'X...X X...X X...X X...X X...X .X.X. ..X..'),
    ('w', 'W', 'X...X X...X X...X X.X.X X.X.X XX.XX X...X'),
    ('x', 'XΧ', 'X...X X...X .X.X. ..X.. .X.X. X...X X...X'),
    ('y', 'YΥ', 'X...X X...X .X.X. ..X.. ..X.. ..X.. ..X..'),
    ('z', 'ZΖ', 'XXXXX ....X ...X. ..X.. .X... X.... XXXXX'),
    ('n0', '0', '.XXX. X...X X..XX X.X.X XX..X X...X .XXX.'),
    ('n1', '1', '..X.. .XX.. ..X.. ..X.. ..X.. ..X.. .XXX.'),
    ('n2', '2', '.XXX. X...X ....X ...X. ..X.. .X... XXXXX'),
    ('n3', '3', 'XXXX. ....X ....X .XXX. ....X ....X XXXX.'),
    ('n4', '4', '...X. ..XX. .X.X. X..X. XXXXX ...X. ...X.'),
    ('n5', '5', 'XXXXX X.... XXXX. ....X ....X X...X .XXX.'),
    ('n6', '6', '.XXX. X.... X.... XXXX. X...X X...X .XXX.'),
    ('n7', '7', 'XXXXX ....X ...X. ..X.. .X... .X... .X...'),
    ('n8', '8', '.XXX. X...X X...X .XXX. X...X X...X .XXX.'),
    ('n9', '9', '.XXX. X...X X...X .XXXX ....X ....X .XXX.'),
    ('gamma', 'Γ', 'XXXXX X.... X.... X.... X.... X.... X....'),
    ('delta', 'Δ', '..X.. .X.X. .X.X. X...X X...X X...X XXXXX'),
    ('theta', 'Θ', '.XXX. X...X X...X XXXXX X...X X...X .XXX.'),
    ('lambda', 'Λ', '..X.. .X.X. .X.X. X...X X...X X...X X...X'),
    ('xi', 'Ξ', 'XXXXX ..... ..... .XXX. ..... ..... XXXXX'),
    ('pi', 'Π', 'XXXXX X...X X...X X...X X...X X...X X...X'),
    ('sigma', 'Σ', 'XXXXX .X... ..X.. ...X. ..X.. .X... XXXXX'),
    ('phi', 'Φ', '..X.. .XXX. X.X.X X.X.X X.X.X .XXX. ..X..'),
    ('psi', 'Ψ', 'X.X.X X.X.X X.X.X .XXX. ..X.. ..X.. ..X..'),
    ('omega', 'Ω', '.XXX. X...X X...X X...X .X.X. .X.X. XX.XX'),
    ('dot', '.,', '..... ..... ..... ..... ..... .XX.. .XX..'),
    ('colon', ':', '..... .XX.. .XX.. ..... .XX.. .XX.. .....'),
    ('minus', '-', '..... ..... ..... XXXXX ..... ..... .....'),
    ('excl', '!', '..X.. ..X.. ..X.. ..X.. ..X.. ..... ..X..'),
    ('quest', '?;', '.XXX. X...X ....X ...X. ..X.. ..... ..X..'),
    ('slash', '/', '....X ....X ...X. ..X.. .X... X.... X....'),
    ('left', '←', '..... ..X.. .X... XXXXX .X... ..X.. .....'),
    ('right', '→', '..... ..X.. ...X. XXXXX ...X. ..X.. .....'),
    ('up', '↑', '..X.. .XXX. X.X.X ..X.. ..X.. ..X.. .....'),
    ('down', '↓', '..... ..X.. ..X.. ..X.. X.X.X .XXX. ..X..'),
]
FONT_GLYPHS = [(name, chars) for name, chars, _ in FONT_ART]


def font_glyph(rows):
    """5x7 rows -> 8 bytes."""
    out = []
    for row in rows.split() + ["....."]:
        b = 0
        for x, ch in enumerate(row):
            if ch == "X":
                b |= 0x40 >> x
        out.append(b | (b >> 1))
    return out


def font_bytes():
    return [(name, font_glyph(rows)) for name, _, rows in FONT_ART]


# ---------------------------------------------------------------------------
# HUD (columns 24-31): a blue panel and a railway down its right edge; the
# icons, 8x8, in ink only: the panel's blue is their paper. A power-up's icon
# is dark (black ink) while it is not running.
# ---------------------------------------------------------------------------
HUD_ICON_ART = """
:coin Y
..XXXX..
.XX..XX.
XX.XX.XX
XX.XXXXX
XX.XXXXX
XX.XX.XX
.XX..XX.
..XXXX..
:life R
........
.XX..XX.
XXXXXXXX
XXXXXXXX
.XXXXXX.
..XXXX..
...XX...
........
:magnet R
XX....XX
XX....XX
XX....XX
XX....XX
XXX..XXX
.XXXXXX.
..XXXX..
........
:turbo Y
...XX...
..XXXX..
.XX..XX.
XX.XX.XX
..XXXX..
.XX..XX.
XX....XX
........
:slow C
XXXXXXXX
.X....X.
..XXXX..
...XX...
...XX...
..X..X..
.XXXXXX.
XXXXXXXX
:spring G
XXXXXXX.
......XX
.XXXXXX.
XX......
.XXXXXX.
......XX
XXXXXXX.
........
:helmet Y
..XXXX..
.XXXXXX.
XXXXXXXX
XXXXXXXX
XXXXXXXX
........
XXXXXXXX
........
:ticket W
XXXXXXXX
X......X
X.XX.X.X
X..X.X.X
X.X...XX
X.XX.X.X
X......X
XXXXXXXX
"""
HUD_POWERUPS = ["magnet", "turbo", "slow", "spring", "helmet", "ticket"]

# the railway: two rails, a sleeper every four lines
HUD_RAIL = ["XXXXXXXX", ".X....X.", ".X....X.", ".X....X."] * 2


def hud_icons():
    return parse_sprites(HUD_ICON_ART)


# ---------------------------------------------------------------------------
# The logo: the CPC's (gfx/logo_cpc.png, 144x48), a colour per cell: the one
# most of its letter pixels have (the CPC's shading inside a cell goes), on
# black; its dark blue shadow is left out.
# ---------------------------------------------------------------------------
LOGO_COLOURS = {                        # the CPC sheet's palette -> letters
    (0, 0, 0): "k", (0, 0, 128): "k", (128, 128, 128): "w", (255, 255, 255): "W",
    (128, 0, 0): "r", (255, 128, 0): "R", (255, 255, 0): "Y", (0, 128, 0): "G",
    (255, 0, 0): "R",
}


def logo():
    import os
    from PIL import Image
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "gfx", "logo_cpc.png")
    im = Image.open(path).convert("RGB")
    w, h = im.size
    img = Img(w, h)
    px = im.load()
    for cy in range(h // 8):
        for cx in range(w // 8):
            cell = [LOGO_COLOURS[px[cx * 8 + x, cy * 8 + y]] for y in range(8) for x in range(8)]
            inks = [c for c in cell if c != "k"]
            ink = max(set(inks), key=inks.count) if inks else "k"
            for y in range(8):
                for x in range(8):
                    if cell[y * 8 + x] != "k":
                        img.px(cx * 8 + x, cy * 8 + y, ink)
    return img
