"""Generate all released BikeHunt browser/app icons from one SVG master.

The SVG in web/icons/favicon.svg is the maintained brand artwork.
During a public site build, CairoSVG produces every PNG and a multi-size ICO.
Existing checked-in raster files are not copied through to production.
"""
from __future__ import annotations

import struct
from pathlib import Path


PNG_OUTPUTS = {
    16: "favicon-16.png",
    32: "favicon-32.png",
    180: "apple-touch-icon.png",
    192: "icon-192.png",
    512: "icon-512.png",
}
ICO_SIZES = (16, 32, 48)


def export_brand_icons(directory: Path) -> None:
    """Deterministic offline rasterization with no external image requests."""
    try:
        import cairosvg
    except ImportError as exc:
        raise RuntimeError("Install requirements-dev.txt to build BikeHunt Pages icons.") from exc
    directory = Path(directory)
    source = directory / "favicon.svg"
    if not source.is_file():
        raise FileNotFoundError(f"Missing BikeHunt icon source: {source}")
    vector = source.read_bytes()
    pngs = {}
    for size in sorted(set(PNG_OUTPUTS) | set(ICO_SIZES)):
        binary = cairosvg.svg2png(bytestring=vector, output_width=size, output_height=size)
        if not binary.startswith(b"\x89PNG\r\n\x1a\n") or struct.unpack(">II", binary[16:24]) != (size, size):
            raise ValueError(f"Invalid BikeHunt raster at {size}px")
        pngs[size] = binary
        if size in PNG_OUTPUTS:
            (directory / PNG_OUTPUTS[size]).write_bytes(binary)

    # PNG-backed ICO entries are supported by modern Windows browsers.
    table = bytearray(struct.pack("<HHH", 0, 1, len(ICO_SIZES)))
    payload = bytearray()
    offset = 6 + 16 * len(ICO_SIZES)
    for size in ICO_SIZES:
        binary = pngs[size]
        table.extend(struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(binary), offset))
        payload.extend(binary)
        offset += len(binary)
    (directory / "favicon.ico").write_bytes(table + payload)
