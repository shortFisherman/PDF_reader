"""Generate the release icons used by both frozen executables.

The repository ships no ``.ico`` and P2-01 may not touch ``static/``, so the build
renders deterministic icons from code: a known-good ICO container holding PNG frames
at the Windows sizes.  Writing a real container keeps the build free of binary blobs
whose provenance nobody can re-derive later.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

ICON_SIZES: tuple[int, ...] = (16, 32, 48, 64, 128, 256)
BACKGROUND = (23, 78, 166)
BACKGROUND_EDGE = (13, 47, 102)
SHEET = (255, 255, 255)
ACCENT = (214, 69, 65)


def _rounded_alpha(x: int, y: int, size: int, radius: int) -> float:
    """Anti-aliased coverage for a rounded square, sampled 1px inside the border."""

    cx = min(max(x + 0.5, radius), size - radius)
    cy = min(max(y + 0.5, radius), size - radius)
    dx = x + 0.5 - cx
    dy = y + 0.5 - cy
    distance = (dx * dx + dy * dy) ** 0.5
    if distance <= radius - 0.75:
        return 1.0
    if distance >= radius + 0.75:
        return 0.0
    return (radius + 0.75 - distance) / 1.5


def _blend(base: tuple[int, int, int, int], colour: tuple[int, int, int], alpha: float) -> tuple[int, int, int, int]:
    if alpha <= 0.0:
        return base
    red = int(round(base[0] * (1 - alpha) + colour[0] * alpha))
    green = int(round(base[1] * (1 - alpha) + colour[1] * alpha))
    blue = int(round(base[2] * (1 - alpha) + colour[2] * alpha))
    out_alpha = int(round(base[3] + (255 - base[3]) * alpha))
    return red, green, blue, out_alpha


def render_icon(size: int) -> bytes:
    """Render one RGBA frame: rounded blue tile, white page, red accent bar."""

    radius = max(2.0, size * 0.22)
    page_left = int(size * 0.30)
    page_right = int(size * 0.70)
    page_top = int(size * 0.20)
    page_bottom = int(size * 0.80)
    bar_top = int(size * 0.36)
    bar_bottom = bar_top + max(1, int(size * 0.10))
    rows: list[bytes] = []
    for y in range(size):
        row = bytearray()
        row.append(0)  # PNG filter type: none
        for x in range(size):
            pixel = (0, 0, 0, 0)
            coverage = _rounded_alpha(x, y, size, radius)
            if coverage > 0.0:
                edge = BACKGROUND_EDGE if min(x, y, size - 1 - x, size - 1 - y) < max(1, size * 0.04) else BACKGROUND
                pixel = _blend(pixel, edge, coverage)
            if page_left <= x < page_right and page_top <= y < page_bottom:
                margin = max(1, int(size * 0.04))
                inner = page_left + margin <= x < page_right - margin and page_top + margin <= y < page_bottom - margin
                pixel = _blend(pixel, SHEET, 1.0 if inner else 0.75)
            if page_left <= x < page_right and bar_top <= y < bar_bottom:
                pixel = _blend(pixel, ACCENT, 0.95)
            row.extend(pixel)
        rows.append(bytes(row))
    return _encode_png(size, size, b"".join(rows))


def _encode_png(width: int, height: int, raw: bytes) -> bytes:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", header),
            chunk(b"IDAT", zlib.compress(raw, 9)),
            chunk(b"IEND", b""),
        )
    )


def build_ico(sizes: tuple[int, ...] = ICON_SIZES) -> bytes:
    """Assemble a PNG-compressed ICO container (supported since Windows Vista)."""

    frames = [(size, render_icon(size)) for size in sizes]
    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = len(header) + 16 * len(frames)
    entries = bytearray()
    body = bytearray()
    for size, payload in frames:
        dimension = 0 if size >= 256 else size
        entries.extend(struct.pack("<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(payload), offset))
        body.extend(payload)
        offset += len(payload)
    return header + bytes(entries) + bytes(body)


def write_icon(path: Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(build_ico())
    return destination
