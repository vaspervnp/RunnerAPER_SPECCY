#!/usr/bin/env python3
"""Put the game on a .TAP tape: a BASIC loader, an optional SCREEN$, the code.

    tools/mktap.py build/loukoumas.tap --sym build/loukoumas.sym \\
        --basic src/loader.bas LOUKOUMAS \\
        --code build/loukoumas.bin LOUKOUMAS LOAD_ADDR

The loader is kept in the repository as plain text with ordinary newlines,
the way src/louk.bas was on the CPC, and tokenised here. Anything in braces
in it - {LOAD_CLEAR} - is a symbol out of the rasm symbol file, so the CLEAR
and the USR address come from config.asm and cannot drift away from it.

--tzx writes the same blocks as a .TZX as well: a "ZXTape!" header and each
block as a standard-speed data block (ID #10) with a second of silence after
it, which is what a tape deck would have between them.

A .TAP is a list of blocks, each a little-endian length and then the bytes
the ROM's LD-BYTES sees: a flag byte (#00 header, #FF data), the data, and an
XOR of all of it. A header is 17 bytes: type, ten characters of name, the
length, and two parameters whose meaning depends on the type.
"""

import argparse
import re
import struct
import sys

# The 48K's keywords, #A5 to #FF. Order matters only for the longest match.
TOKENS = [
    "RND", "INKEY$", "PI", "FN", "POINT", "SCREEN$", "ATTR", "AT", "TAB",
    "VAL$", "CODE", "VAL", "LEN", "SIN", "COS", "TAN", "ASN", "ACS", "ATN",
    "LN", "EXP", "INT", "SQR", "SGN", "ABS", "PEEK", "IN", "USR", "STR$",
    "CHR$", "NOT", "BIN", "OR", "AND", "<=", ">=", "<>", "LINE", "THEN", "TO",
    "STEP", "DEF FN", "CAT", "FORMAT", "MOVE", "ERASE", "OPEN #", "CLOSE #",
    "MERGE", "VERIFY", "BEEP", "CIRCLE", "INK", "PAPER", "FLASH", "BRIGHT",
    "INVERSE", "OVER", "OUT", "LPRINT", "LLIST", "STOP", "READ", "DATA",
    "RESTORE", "NEW", "BORDER", "CONTINUE", "DIM", "REM", "FOR", "GO TO",
    "GO SUB", "INPUT", "LOAD", "LIST", "LET", "PAUSE", "NEXT", "POKE", "PRINT",
    "PLOT", "RUN", "SAVE", "RANDOMIZE", "IF", "CLS", "DRAW", "CLEAR", "RETURN",
    "COPY",
]
TOKEN = {name: 0xA5 + i for i, name in enumerate(TOKENS)}
assert TOKEN["COPY"] == 0xFF and TOKEN["SCREEN$"] == 0xAA
BY_LENGTH = sorted(TOKENS, key=len, reverse=True)


def number(text):
    """A number literal as the editor stores it: the digits as typed, then
    #0E and the value in the ROM's five-byte form. Whole numbers in
    -65535..65535 have a short form of their own, and that is all a loader
    needs."""
    v = int(text)
    if not -65535 <= v <= 65535:
        sys.exit("mktap: %s is out of the small-integer range" % text)
    sign = 0xFF if v < 0 else 0x00
    return text.encode() + bytes([0x0E, 0x00, sign]) + struct.pack("<H", v & 0xFFFF) + b"\x00"


def tokenise_line(text, lineno):
    out = bytearray()
    i = 0
    while i < len(text):
        c = text[i]
        if c == '"':
            j = text.index('"', i + 1)
            out += text[i:j + 1].encode("ascii")
            i = j + 1
            continue
        if c == " ":
            i += 1                              # the ROM stores no spaces
            continue                            # between tokens
        for kw in BY_LENGTH:
            n = len(kw)
            if text[i:i + n].upper() == kw:
                # a keyword ending in a letter must not run on into a name
                if kw[-1].isalpha() and i + n < len(text) and text[i + n].isalnum():
                    continue
                if kw[0].isalpha() and i > 0 and text[i - 1].isalnum():
                    continue
                out.append(TOKEN[kw])
                i += n
                if kw == "REM":
                    out += text[i:].encode("ascii")
                    i = len(text)
                break
        else:
            m = re.match(r"\d+", text[i:])
            if m and not (i > 0 and text[i - 1].isalpha()):
                out += number(m.group())
                i += len(m.group())
            else:
                out += c.encode("ascii")
                i += 1
    out.append(0x0D)
    return struct.pack(">H", lineno) + struct.pack("<H", len(out)) + bytes(out)


def tokenise(source, symbols):
    prog = bytearray()
    first = None
    for raw in source.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        raw = re.sub(r"\{(\w+)\}", lambda m: str(symbols[m.group(1).upper()]), raw)
        m = re.match(r"(\d+)\s*(.*)", raw)
        if not m:
            sys.exit("mktap: a BASIC line without a number: %r" % raw)
        n = int(m.group(1))
        first = n if first is None else first
        prog += tokenise_line(m.group(2), n)
    return bytes(prog), first


def block(flag, data):
    body = bytes([flag]) + data
    x = 0
    for b in body:
        x ^= b
    body += bytes([x])
    return struct.pack("<H", len(body)) + body


def header(kind, name, length, p1, p2):
    name = name.encode("ascii")[:10].ljust(10)
    return block(0x00, bytes([kind]) + name + struct.pack("<HHH", length, p1, p2))


def read_symbols(path):
    sym = {}
    with open(path) as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 2 and parts[1].startswith("#"):
                sym[parts[0].upper()] = int(parts[1][1:], 16)
    return sym


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tap")
    ap.add_argument("--sym", help="rasm symbol file, for {NAME} in the loader")
    ap.add_argument("--basic", nargs=2, metavar=("FILE", "NAME"))
    ap.add_argument("--screen", nargs=2, metavar=("FILE", "NAME"),
                    help="a 6912-byte SCREEN$, loaded at #4000")
    ap.add_argument("--tzx", help="and the same tape as a .TZX here")
    ap.add_argument("--code", nargs=3, action="append", default=[],
                    metavar=("FILE", "NAME", "ADDR"),
                    help="ADDR is a number or a symbol")
    args = ap.parse_args()

    symbols = read_symbols(args.sym) if args.sym else {}
    out = bytearray()

    if args.basic:
        prog, first = tokenise(open(args.basic[0]).read(), symbols)
        out += header(0, args.basic[1], len(prog), first, len(prog))
        out += block(0xFF, prog)

    if args.screen:
        scr = open(args.screen[0], "rb").read()
        if len(scr) != 6912:
            sys.exit("mktap: a SCREEN$ is 6912 bytes, %s is %d" % (args.screen[0], len(scr)))
        out += header(3, args.screen[1], 6912, 0x4000, 0x8000)
        out += block(0xFF, scr)

    for path, name, addr in args.code:
        data = open(path, "rb").read()
        a = int(addr, 0) if addr[0].isdigit() else symbols[addr.upper()]
        out += header(3, name, len(data), a, 0x8000)
        out += block(0xFF, data)

    open(args.tap, "wb").write(out)
    print("wrote %s, %d bytes" % (args.tap, len(out)))
    if args.tzx:
        tzx = bytearray(b"ZXTape!\x1a\x01\x14")
        i = 0
        while i < len(out):
            n = out[i] | (out[i + 1] << 8)
            tzx += bytes([0x10]) + struct.pack("<HH", 1000, n) + out[i + 2:i + 2 + n]
            i += 2 + n
        open(args.tzx, "wb").write(tzx)
        print("wrote %s, %d bytes" % (args.tzx, len(tzx)))


if __name__ == "__main__":
    main()
