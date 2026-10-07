"""(From the CPC version, unchanged but for where the tile names come from.)

Compiles track chunks (levels/chunks/*.txt) into src/data/chunks.asm.

Chunk file format:

    # chunk: train_mid_ramp
    # env: any            (any | urban | forest)
    # diff: 2             (1-5, minimum difficulty)
    # weight: 3           (relative probability)
    ..c  v..  ...
    ..c  W1c  ..c
    ...  W1.  ...
    ...  ^..  S..
    ...  ^..  S..

Grid rows are listed top to bottom as they appear on screen (the last line
is the first one the player meets). Each lane cell has 3 characters:

  object  '.' rail
          'T' train, locomotive first: its cab faces the player (bottom)
          'R' train, locomotive last: the player meets a wagon end first
          '^' ramp up (3 rows, below a train)   'v' ramp down (3 rows, above a train)
          'S' buffer stop (2 rows)   'F' signal (2 rows)
  type    train livery 1-3 for T/R, '.' otherwise
  item    '.' none  'c' coin. Power-ups are not part of chunks: the game
          places one every 100-200 rows (src/world.asm place_powerup).

A row has coins in one lane at most (never side by side in 2 or 3 lanes).
Coins come in runs of MIN_COIN_RUN to MAX_COIN_RUN coins in one lane, one
coin every COIN_STEP rows (an empty row between two coins); two coins are
never on consecutive rows of a lane.

A chunk with a ramp up says how it rewards or forces the ramp:

    # ramp: coins    most coins (RAMP_ROOF_SHARE) on the train roofs
    # ramp: blocked  buffer stops in every other lane along the train, one
                     per BLOCK_ROWS rows at least (where the third lane is
                     open: a row always has a lane without obstacles)

Each ramp chunk comes as a pair "<name>_coins" / "<name>_blocked" with
weights 1:2, so a ramp brings coins a third of the time.

Trains are long: a locomotive of LOCO_ROWS rows and at least MIN_WAGONS
wagons of WAGON_ROWS rows, joined by 1-row couplers (collision COL_GAP: a
train at ground level, a gap on the roofs in hard mode). No coins on the
couplers. A T/R run must be
exactly LOCO_ROWS + k * (1 + WAGON_ROWS) rows with k >= MIN_WAGONS
(50 rows for 2 wagons, 69 for 3, ...).

In the game every chunk gets a random lane order (any of the six, or only
as written / mirrored when it has trains side by side: roof hops need
neighbouring lanes) and a random livery for all its trains
(src/chunk_pick.asm, livery_tiles here), so a chunk can be written with its
train in any lane and livery.
"""

import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zxart as assets  # noqa: E402  (the tiles: the CPC's names, the same order)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHUNK_DIR = os.path.join(ROOT, "levels", "chunks")
OUT = os.path.join(ROOT, "src", "data", "chunks.asm")

TILE = {name: index for index, name in enumerate(assets.TRACK_TILES)}
# liveries: blocks of tiles in this order (the game's livery_tiles tables)
WAGON_PARTS = ("end_bottom", "body_a", "body_b", "end_top", "coupler")
LOCO_PARTS = ("nose", "body", "pantograph", "nose_top")
WAGON_TILES, LOCO_TILES = len(WAGON_PARTS), len(LOCO_PARTS)
assert all(TILE[f"wagon{t}_{p}"] == TILE["wagon1_end_bottom"] + (t - 1) * WAGON_TILES + i
           for t in (1, 2, 3) for i, p in enumerate(WAGON_PARTS))
assert all(TILE[f"loco{t}_{p}"] == TILE["loco1_nose"] + (t - 1) * LOCO_TILES + i
           for t in (1, 2, 3) for i, p in enumerate(LOCO_PARTS))
assert TILE["loco1_nose"] == TILE["wagon1_end_bottom"] + 3 * WAGON_TILES
assert TILE["ramp_up_0"] == TILE["loco1_nose"] + 3 * LOCO_TILES

# collision classes (low nibble) - see src/world.asm
COL_NONE, COL_STOP, COL_SIGNAL, COL_TRAIN, COL_NOSE, COL_RAMP_UP, COL_RAMP_DOWN, COL_GAP = range(8)
ITEMS = {".": 0, "c": 1}
ITEM_ROWS = {0: 0, 1: 1}                       # rows an item overlay covers (default 2)
ENVS = {"any": 0, "urban": 1, "forest": 2}

WAGON_ROWS = 18
LOCO_ROWS = 12
MIN_WAGONS = 2
MIN_COIN_RUN = 3
MAX_COIN_RUN = 10
COIN_STEP = 2
RAMP_ROOF_SHARE = 0.6
BLOCK_ROWS = 12
RAMP_KINDS = ("coins", "blocked")


def train_length(wagons):
    return LOCO_ROWS + wagons * (1 + WAGON_ROWS)


def tile_collision(name):
    """The collision class of a track tile (each tile has one)."""
    if name.startswith(("rail", "signal_1")):
        return COL_NONE
    if name.startswith("stop"):
        return COL_STOP
    if name == "signal_0":
        return COL_SIGNAL
    if name.endswith("coupler"):
        return COL_GAP
    if name.endswith("_nose"):
        return COL_NOSE
    if name.startswith(("wagon", "loco")):
        return COL_TRAIN
    kind, k = name.rsplit("_", 1)                # ramp_up_k / ramp_down_k
    return (COL_RAMP_UP if kind == "ramp_up" else COL_RAMP_DOWN) | (int(k) << 4)


TILE_COLLISION = [tile_collision(name) for name in assets.TRACK_TILES]


def livery_tile(tile, shift):
    """A train tile in the livery `shift` further on (other tiles stay)."""
    for first, size in ((TILE["wagon1_end_bottom"], WAGON_TILES), (TILE["loco1_nose"], LOCO_TILES)):
        if first <= tile < first + 3 * size:
            livery, part = divmod(tile - first, size)
            return first + (livery + shift) % 3 * size + part
    return tile


class LevelError(Exception):
    pass


def parse(path):
    header, grid = {}, []
    with open(path) as f:
        for number, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if not line.strip():
                continue
            if line.startswith("#"):
                if ":" in line:
                    key, value = line[1:].split(":", 1)
                    header[key.strip()] = value.strip()
                continue
            cells = line.split()
            if len(cells) != 3 or any(len(c) != 3 for c in cells):
                raise LevelError(f"{path}:{number}: expected 3 cells of 3 characters, got {line!r}")
            grid.append((number, cells))
    if not grid:
        raise LevelError(f"{path}: empty chunk")
    return header, list(reversed(grid))        # bottom row first


def _runs(column):
    """[(start, length, object, type)] of consecutive equal object+type cells."""
    runs, start = [], 0
    for i in range(1, len(column) + 1):
        if i == len(column) or column[i][:2] != column[start][:2]:
            runs.append((start, i - start, column[start][0], column[start][1]))
            start = i
    return runs


def _train_type(path, row, t):
    if t not in "123":
        raise LevelError(f"{path}: row {row}: train cells need a livery 1-3, got {t!r}")
    return int(t)


def resolve_lane(path, column, lane):
    """column: cells bottom to top -> [(tile index, collision)]"""
    out = [None] * len(column)
    for start, length, obj, t in _runs(column):
        rows = range(start, start + length)
        where = f"lane {lane + 1}, rows {start}-{start + length - 1} from the bottom"
        if obj == ".":
            for r in rows:
                out[r] = (TILE["rail_b" if (r * 7 + lane * 3) % 11 == 0 else "rail_a"], COL_NONE)
        elif obj in "TR":
            tt = _train_type(path, start, t)
            wagons, rest = divmod(length - LOCO_ROWS, 1 + WAGON_ROWS)
            if length < LOCO_ROWS or rest or wagons < MIN_WAGONS:
                valid = ", ".join(str(train_length(k)) for k in range(MIN_WAGONS, MIN_WAGONS + 3))
                raise LevelError(f"{path}: {where}: a train needs a locomotive and at least {MIN_WAGONS} wagons: "
                                 f"{length} rows, valid lengths are {valid}, ...")
            parts = []                               # bottom to top, as (tile name, collision)
            wagon = ([f"wagon{tt}_end_bottom"]
                     + [f"wagon{tt}_body_{'a' if k % 3 == 1 else 'b'}" for k in range(WAGON_ROWS - 2)]
                     + [f"wagon{tt}_end_top"])
            if obj == "T":                           # cab at the bottom, back end at the top
                parts += ([(f"loco{tt}_nose", COL_NOSE)]
                          + [(f"loco{tt}_{'pantograph' if k in (2, LOCO_ROWS - 4) else 'body'}", COL_TRAIN)
                             for k in range(1, LOCO_ROWS - 1)]
                          + [(f"wagon{tt}_end_top", COL_TRAIN)])
                for _ in range(wagons):
                    parts += [(f"wagon{tt}_coupler", COL_GAP)] + [(n, COL_TRAIN) for n in wagon]
            else:                                    # wagons first, cab facing away at the top
                for _ in range(wagons):
                    parts += [(n, COL_TRAIN) for n in wagon] + [(f"wagon{tt}_coupler", COL_GAP)]
                parts += ([(f"wagon{tt}_end_bottom", COL_TRAIN)]
                          + [(f"loco{tt}_{'pantograph' if k in (3, LOCO_ROWS - 3) else 'body'}", COL_TRAIN)
                             for k in range(1, LOCO_ROWS - 1)]
                          + [(f"loco{tt}_nose_top", COL_TRAIN)])
            for r, (name, collision) in zip(rows, parts):
                out[r] = (TILE[name], collision)
        elif obj in "^v":
            if length != 3:
                raise LevelError(f"{path}: {where}: ramps are exactly 3 rows")
            neighbour = start + 3 if obj == "^" else start - 1
            if not (0 <= neighbour < len(column)) or column[neighbour][0] not in "TR":
                raise LevelError(f"{path}: {where}: ramp {'up must sit below' if obj == '^' else 'down must sit above'} a train")
            for k, r in enumerate(rows):
                name = f"ramp_{'up' if obj == '^' else 'down'}_{k}"
                out[r] = (TILE[name], (COL_RAMP_UP if obj == "^" else COL_RAMP_DOWN) | (k << 4))
        elif obj == "S":
            if length != 2:
                raise LevelError(f"{path}: {where}: a buffer stop is exactly 2 rows")
            out[start] = (TILE["stop_0"], COL_STOP)
            out[start + 1] = (TILE["stop_1"], COL_STOP)
        elif obj == "F":
            if length != 2:
                raise LevelError(f"{path}: {where}: a signal is exactly 2 rows")
            out[start] = (TILE["signal_1"], COL_NONE)      # stop line
            out[start + 1] = (TILE["signal_0"], COL_SIGNAL)  # gantry with the lamp
        else:
            raise LevelError(f"{path}: {where}: unknown object {obj!r}")
    return out


def compile_chunk(path):
    header, grid = parse(path)
    name = header.get("chunk") or os.path.splitext(os.path.basename(path))[0]
    env = header.get("env", "any")
    if env not in ENVS:
        raise LevelError(f"{path}: env must be one of {', '.join(ENVS)}")
    diff = int(header.get("diff", 1))
    weight = int(header.get("weight", 1))
    if not 1 <= diff <= 5 or not 1 <= weight <= 15:
        raise LevelError(f"{path}: diff 1-5 and weight 1-15")
    columns = [[cells[lane] for _, cells in grid] for lane in range(3)]
    lanes = [resolve_lane(path, col, lane) for lane, col in enumerate(columns)]
    rows = []
    for r in range(len(grid)):
        row = []
        for lane in range(3):
            item_char = columns[lane][r][2]
            if item_char not in ITEMS:
                raise LevelError(f"{path}: line {grid[r][0]}: unknown item {item_char!r} "
                                 f"(chunks hold coins only; the game places the power-ups)")
            item = ITEMS[item_char]
            tile, collision = lanes[lane][r]
            row += [tile, collision, item]
        for lane in range(3):
            if row[lane * 3 + 2] == ITEMS["c"] and row[lane * 3 + 1] == COL_GAP:
                raise LevelError(f"{path}: line {grid[r][0]}: a coin between two wagons (lane {lane + 1})")
        for lane in range(3):                     # (the game derives it from the tile)
            assert row[lane * 3 + 1] == TILE_COLLISION[row[lane * 3]], (path, r, lane)
        coin_lanes = sum(1 for lane in range(3) if row[lane * 3 + 2] == ITEMS["c"])
        if coin_lanes > 1:
            raise LevelError(f"{path}: line {grid[r][0]}: coins in {coin_lanes} lanes - a row has coins in one lane only")
        rows.append(row)
    for lane in range(3):
        for start, length in coin_runs([cell[2] == "c" for cell in columns[lane]], path, grid, lane):
            if not MIN_COIN_RUN <= length <= MAX_COIN_RUN:
                raise LevelError(f"{path}: line {grid[start][0]}: {length} coin(s) in lane {lane + 1} - "
                                 f"coins come in runs of {MIN_COIN_RUN} to {MAX_COIN_RUN}")
    ramp = check_ramp(path, header, columns)
    return {"name": name, "env": ENVS[env], "diff": diff, "weight": weight, "rows": rows, "ramp": ramp,
            "side_by_side": side_by_side(columns)}


def side_by_side(columns):
    """Trains (or their ramps) in two neighbouring lanes on the same row: the
    game keeps the lanes' order (or mirrors it) so the roof hops stay."""
    return any(columns[a][r][0] in "TR^v" and columns[a + 1][r][0] in "TR^v"
               for a in (0, 1) for r in range(len(columns[0])))


def coin_runs(column, path="", grid=None, lane=0):
    """[(first row, coins)] of a lane's coin runs (bottom first): one coin
    every COIN_STEP rows. Coins on consecutive rows are rejected."""
    rows = [r for r, has in enumerate(column) if has]
    runs = []
    for r in rows:
        if runs and r - runs[-1][2] < COIN_STEP:
            line = grid[r][0] if grid else r
            raise LevelError(f"{path}: line {line}: coins on consecutive rows in lane {lane + 1} - "
                             f"leave an empty row between two coins")
        if runs and r - runs[-1][2] == COIN_STEP:
            runs[-1][1] += 1
            runs[-1][2] = r
        else:
            runs.append([r, 1, r])
    return [(start, count) for start, count, _ in runs]


def check_ramp(path, header, columns):
    """The "ramp" header of a chunk with a ramp up (None without one)."""
    ramp_lanes = [lane for lane in range(3) if any(cell[0] == "^" for cell in columns[lane])]
    kind = header.get("ramp")
    if not ramp_lanes:
        if kind:
            raise LevelError(f"{path}: 'ramp: {kind}' without a ramp up")
        return None
    if kind not in RAMP_KINDS:
        raise LevelError(f"{path}: a chunk with a ramp up needs 'ramp: coins' or 'ramp: blocked'")
    coins = [(lane, r) for lane in range(3) for r, cell in enumerate(columns[lane]) if cell[2] == "c"]
    if kind == "coins":
        roof = [c for c in coins if columns[c[0]][c[1]][0] in "TR"]
        if len(roof) < RAMP_ROOF_SHARE * len(coins) or not coins:
            raise LevelError(f"{path}: 'ramp: coins' needs at least {RAMP_ROOF_SHARE:.0%} of the coins on "
                             f"the train roofs ({len(roof)} of {len(coins)})")
        return kind
    for lane in ramp_lanes:                      # blocked: stops next to the train
        column = columns[lane]
        first = min(r for r, cell in enumerate(column) if cell[0] == "^")
        last = max(r for r, cell in enumerate(column) if cell[0] in "TR")
        for other in range(3):
            third = 3 - lane - other            # stops only where it stays open
            free = [r for r in range(first, last + 1)
                    if columns[other][r][0] not in "TR^v" and columns[third][r][0] not in "TRSF"]
            if other == lane or len(free) < BLOCK_ROWS:
                continue
            stops = sum(1 for r in free if columns[other][r][0] == "S") // 2
            if stops < len(free) // BLOCK_ROWS:
                raise LevelError(f"{path}: 'ramp: blocked' needs a buffer stop every {BLOCK_ROWS} rows in "
                                 f"lane {other + 1} next to the train ({stops} for {len(free)} rows)")
    return kind


def asm_source(chunks):
    lines = ["; generated by tools/mklevel.py from levels/chunks/ - do not edit",
             f"CHUNK_COUNT equ {len(chunks)}",
             f"TILE_RAIL_A equ {TILE['rail_a']}                  ; empty track (src/world.asm spacer_row)",
             f"TILE_WAGONS equ {TILE['wagon1_end_bottom']}                  ; wagon tiles, {WAGON_TILES} per livery",
             f"TILE_LOCOS equ {TILE['loco1_nose']}                  ; locomotive tiles, {LOCO_TILES} per livery",
             f"TILE_RAMPS equ {TILE['ramp_up_0']}                  ; after the trains",
             "CHUNK_ENV equ #3F",
             "CHUNK_RAMP equ #40                ; a ramp up: power-ups on the roofs too",
             "CHUNK_SIDE_BY_SIDE equ #80        ; trains side by side: lane order kept or mirrored",
             "; chunk: rows, min difficulty, weight, env (0 any, 1 urban, 2 forest) | ramp | side by side,",
             ";        then per row bottom to top: 3 cells, track tile + #80 with a coin",
             ";        (the collision class comes from the tile: tile_collision)",
             "chunk_table:"]
    lines += [f"                defw chunk_{c['name']}" for c in chunks]
    lines += ["; track tile -> the same tile with the livery moved on by 0, 1, 2 (64 each)",
              "                align 256",
              "livery_tiles:"]
    for shift in range(3):
        table = [livery_tile(t, shift) for t in range(64)]
        for i in range(0, 64, 16):
            lines.append("                defb " + ",".join(str(v) for v in table[i:i + 16]))
    lines += ["; track tile -> its collision class (same page: livery_tiles + TILE_COLL_OFS)",
              "TILE_COLL_OFS equ 192",
              "tile_collision:"]
    table = TILE_COLLISION + [0] * (64 - len(TILE_COLLISION))
    for i in range(0, 64, 16):
        lines.append("                defb " + ",".join(str(v) for v in table[i:i + 16]))
    for c in chunks:
        lines.append(f"chunk_{c['name']}:")
        env = c["env"] | (0x80 if c["side_by_side"] else 0) | (0x40 if c["ramp"] else 0)
        lines.append(f"                defb {len(c['rows'])},{c['diff']},{c['weight']},{env}")
        for row in c["rows"]:
            lines.append("                defb " + ",".join(str(row[lane * 3] | (0x80 if row[lane * 3 + 2] else 0))
                                                         for lane in range(3)))
    return "\n".join(lines) + "\n"


def load_all():
    paths = sorted(glob.glob(os.path.join(CHUNK_DIR, "*.txt")))
    chunks = [compile_chunk(p) for p in paths]
    names = [c["name"] for c in chunks]
    if len(set(names)) != len(names):
        raise LevelError("chunk names must be unique")
    by_name = {c["name"]: c for c in chunks}
    for c in chunks:                             # ramp pairs, weights 1:2
        if c["ramp"] is None:
            continue
        suffix = "_" + c["ramp"]
        if not c["name"].endswith(suffix):
            raise LevelError(f"chunk {c['name']}: a 'ramp: {c['ramp']}' chunk is named <name>{suffix}")
        base = c["name"][:-len(suffix)]
        coins, blocked = by_name.get(base + "_coins"), by_name.get(base + "_blocked")
        if not coins or not blocked:
            raise LevelError(f"chunk {base}: ramp chunks come in pairs {base}_coins / {base}_blocked")
        if blocked["weight"] != 2 * coins["weight"] or (coins["env"], coins["diff"]) != (blocked["env"], blocked["diff"]):
            raise LevelError(f"chunk {base}: _blocked has twice the weight of _coins, same env and diff")
    return chunks


def main():
    try:
        chunks = load_all()
    except LevelError as e:
        print(f"mklevel: {e}", file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write(asm_source(chunks))
    size = sum(4 + 9 * len(c["rows"]) for c in chunks)
    print(f"chunks     {len(chunks):3d} chunks  {size:6d} bytes -> {os.path.relpath(OUT, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
