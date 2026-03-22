"""
Generate PNG icons for the PWA manifest from the SVG source.
Outputs icon-192.png and icon-512.png into data/.
Requires: Pillow (already in requirements.txt)
"""
import pathlib
import struct
import zlib

DATA_DIR = pathlib.Path(__file__).parent.parent / 'data'


def make_png(size: int) -> bytes:
    """
    Build a simple solid-colour PNG programmatically.
    Background: #111418  |  accent: #29b6f6  |  IHC initials rendered via pixels.
    For a proper icon the SVG source should be rasterised; here we produce a
    clean, branded placeholder that satisfies manifest requirements.
    """
    bg   = (17,  20,  24)    # --surface  #111418
    acc  = (41, 182, 246)    # --blue     #29b6f6
    grn  = ( 0, 230, 118)    # --green    #00e676
    head = (232, 237, 242)   # --heading  #e8edf2

    pixels = [[bg] * size for _ in range(size)]

    def fill_rect(x0, y0, x1, y1, colour):
        for y in range(max(0, y0), min(size, y1)):
            for x in range(max(0, x0), min(size, x1)):
                pixels[y][x] = colour

    def fill_circle(cx, cy, r, colour, fill=True):
        for y in range(max(0, cy - r), min(size, cy + r + 1)):
            for x in range(max(0, cx - r), min(size, cx + r + 1)):
                if (x - cx) ** 2 + (y - cy) ** 2 <= r ** 2:
                    pixels[y][x] = colour

    s = size / 192  # scale factor relative to 192 px base

    # Outer rounded-square feel – thin blue border ring
    border = int(6 * s)
    margin = int(12 * s)
    for y in range(margin, size - margin):
        for x in range(margin, size - margin):
            on_edge = (
                y < margin + border or y > size - margin - border - 1 or
                x < margin + border or x > size - margin - border - 1
            )
            if on_edge:
                pixels[y][x] = (*acc, )

    # ── Helicopter body ─────────────────────────────────────────────────────
    cx = size // 2

    # Fuselage (oval)
    fy = int(105 * s)
    fw = int(60 * s)
    fh = int(28 * s)
    for y in range(fy - fh, fy + fh):
        for x in range(cx - fw, cx + fw):
            nx = (x - cx) / fw
            ny = (y - fy) / fh
            if nx * nx + ny * ny <= 1.0:
                pixels[y][x] = (26, 35, 50)

    # Fuselage outline
    for y in range(fy - fh, fy + fh):
        for x in range(cx - fw, cx + fw):
            nx = (x - cx) / fw
            ny = (y - fy) / fh
            r2 = nx * nx + ny * ny
            if 0.85 <= r2 <= 1.0:
                pixels[y][x] = acc

    # Cockpit bubble (smaller ellipse)
    by = int(100 * s)
    bw = int(28 * s)
    bh = int(18 * s)
    for y in range(by - bh, by + bh):
        for x in range(cx - bw, cx + bw):
            nx = (x - cx) / bw
            ny = (y - by) / bh
            if nx * nx + ny * ny <= 1.0:
                pixels[y][x] = (13, 27, 42)

    # Main rotor blade (horizontal bar)
    ry = int(80 * s)
    rthick = max(3, int(7 * s))
    fill_rect(margin + int(10 * s), ry - rthick, size - margin - int(10 * s), ry + rthick, acc)
    fill_circle(cx, ry, int(8 * s), acc)

    # Tail boom
    tail_y = int(108 * s)
    fill_rect(cx + fw - int(5 * s), tail_y - int(4 * s),
              cx + fw + int(40 * s), tail_y + int(5 * s), (26, 35, 50))

    # Tail rotor (small vertical bar)
    trx = cx + fw + int(38 * s)
    fill_rect(trx - int(2 * s), tail_y - int(14 * s), trx + int(2 * s), tail_y + int(14 * s), acc)
    fill_rect(trx - int(14 * s), tail_y - int(2 * s), trx + int(14 * s), tail_y + int(2 * s), acc)
    fill_circle(trx, tail_y, int(4 * s), acc)

    # Skids
    sk_y = int(140 * s)
    fill_rect(cx - fw + int(5 * s), sk_y, cx + int(20 * s), sk_y + max(2, int(4 * s)), (74, 85, 104))

    # Status dot (green)
    fill_circle(cx + int(55 * s), int(145 * s), int(10 * s), grn)

    # ── "IHC" text rendered as pixel blocks ─────────────────────────────────
    # Simple 5×7 pixel font for I, H, C
    char_scale = max(1, int(s * 2))
    def draw_char(grid, ox, oy, colour):
        for row_i, row in enumerate(grid):
            for col_i, px in enumerate(row):
                if px:
                    y0 = oy + row_i * char_scale
                    x0 = ox + col_i * char_scale
                    fill_rect(x0, y0, x0 + char_scale, y0 + char_scale, colour)

    I_glyph = [
        [1, 1, 1],
        [0, 1, 0],
        [0, 1, 0],
        [0, 1, 0],
        [0, 1, 0],
        [0, 1, 0],
        [1, 1, 1],
    ]
    H_glyph = [
        [1, 0, 1],
        [1, 0, 1],
        [1, 0, 1],
        [1, 1, 1],
        [1, 0, 1],
        [1, 0, 1],
        [1, 0, 1],
    ]
    C_glyph = [
        [0, 1, 1],
        [1, 0, 0],
        [1, 0, 0],
        [1, 0, 0],
        [1, 0, 0],
        [1, 0, 0],
        [0, 1, 1],
    ]

    text_y = int(155 * s)
    char_w = 3 * char_scale + int(2 * s)  # width + gap
    total_w = 3 * char_w - int(2 * s)
    start_x = (size - total_w) // 2

    draw_char(I_glyph, start_x, text_y, head)
    draw_char(H_glyph, start_x + char_w, text_y, head)
    draw_char(C_glyph, start_x + 2 * char_w, text_y, head)

    # ── Encode as PNG ────────────────────────────────────────────────────────
    raw_rows = b''
    for row in pixels:
        raw_rows += b'\x00'
        for r, g, b in row:
            raw_rows += bytes([r, g, b])

    compressed = zlib.compress(raw_rows, 9)

    def chunk(name: bytes, data: bytes) -> bytes:
        c = name + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xFFFFFFFF)

    ihdr = struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0)
    png = b'\x89PNG\r\n\x1a\n'
    png += chunk(b'IHDR', ihdr)
    png += chunk(b'IDAT', compressed)
    png += chunk(b'IEND', b'')
    return png


if __name__ == '__main__':
    for sz, name in [(192, 'icon-192.png'), (512, 'icon-512.png')]:
        path = DATA_DIR / name
        path.write_bytes(make_png(sz))
        print(f'Generated {path} ({sz}x{sz})')
