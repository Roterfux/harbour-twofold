"""Render the launcher icon at the Sailfish sizes (standard library only; development only).

    python3 tools/make_icons.py

A rounded square with a countdown ring (three quarters left) and a dot in the middle.
"""
import math
import os
import struct
import zlib

SIZES = (86, 108, 128, 172)
SAMPLES = 4
TOP, BOTTOM = (0x6A, 0x5A, 0xE0), (0x2B, 0x1F, 0x7A)
CORNER = 0.225
RING = (0.24, 0.31)          # inner and outer radius of the ring
DOT = 0.09


def sample(x, y):
    cx = min(max(x, CORNER), 1 - CORNER)
    cy = min(max(y, CORNER), 1 - CORNER)
    if math.hypot(x - cx, y - cy) > CORNER:
        return 0, 0, 0, 0
    dx, dy = x - 0.5, y - 0.5
    far = math.hypot(dx, dy)
    angle = math.atan2(dx, -dy) % (2 * math.pi)     # 0 at the top, clockwise
    ring = RING[0] <= far <= RING[1] and angle >= math.pi / 2
    if far <= DOT or ring:
        return 255, 255, 255, 255
    t = x * 0.35 + y * 0.65
    return tuple(int(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3)) + (255,)


def render(size):
    rows = []
    n = SAMPLES * SAMPLES
    for py in range(size):
        row = bytearray([0])
        for px in range(size):
            acc = [0, 0, 0, 0]
            for sy in range(SAMPLES):
                for sx in range(SAMPLES):
                    r, g, b, a = sample((px + (sx + 0.5) / SAMPLES) / size,
                                        (py + (sy + 0.5) / SAMPLES) / size)
                    acc[0] += r * a
                    acc[1] += g * a
                    acc[2] += b * a
                    acc[3] += a
            alpha = acc[3]
            row += bytes((acc[0] // alpha, acc[1] // alpha, acc[2] // alpha, alpha // n)
                         if alpha else (0, 0, 0, 0))
        rows.append(bytes(row))
    return b"".join(rows)


def chunk(kind, data):
    return (struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))


def png(size):
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(render(size), 9))
            + chunk(b"IEND", b""))


if __name__ == "__main__":
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "icons")
    for s in SIZES:
        folder = os.path.join(root, "%dx%d" % (s, s))
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "harbour-twofold.png"), "wb") as handle:
            handle.write(png(s))
        print("wrote %dx%d" % (s, s))
