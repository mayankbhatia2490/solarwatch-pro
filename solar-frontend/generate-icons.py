#!/usr/bin/env python3
"""
Generate PWA icons for SolarWatch Pro.
Pure Python — no external dependencies.
Colors: #1B2B6B (navy) background, #C9A84C (gold) sun + rays.
"""
import struct, zlib, math, os

def _chunk(tag: bytes, data: bytes) -> bytes:
    c = tag + data
    return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

def _png(pixels: list[list[tuple[int,int,int]]]) -> bytes:
    size = len(pixels)
    raw = b"".join(b"\x00" + bytes(c for px in row for c in px) for row in pixels)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )

def _icon(size: int) -> bytes:
    BG   = (27,  43,  107)   # #1B2B6B — navy
    GOLD = (201, 168,  76)   # #C9A84C — gold
    LGOLD= (220, 190, 110)   # lighter gold for inner sun
    cx = cy = size / 2.0

    r_sun   = size * 0.26    # sun disc radius
    r_ri    = size * 0.31    # ray inner edge
    r_ro    = size * 0.42    # ray outer edge
    ray_hw  = 0.20           # ray half-angle (radians)
    n_rays  = 8

    pixels = []
    for y in range(size):
        row = []
        for x in range(size):
            dx, dy = x - cx, y - cy
            d  = math.hypot(dx, dy)
            th = math.atan2(dy, dx)

            in_ray = any(
                abs(((th - i * math.tau / n_rays + math.pi) % math.tau) - math.pi) < ray_hw
                and r_ri <= d <= r_ro
                for i in range(n_rays)
            )

            if d <= r_sun * 0.65:
                row.append(LGOLD)
            elif d <= r_sun:
                row.append(GOLD)
            elif in_ray:
                row.append(GOLD)
            else:
                row.append(BG)
        pixels.append(row)
    return _png(pixels)

out = os.path.join(os.path.dirname(__file__), "public")
for size, name in [(192, "icon-192.png"), (512, "icon-512.png")]:
    path = os.path.join(out, name)
    with open(path, "wb") as f:
        f.write(_icon(size))
    print(f"✓ {path}  ({size}×{size}px)")
