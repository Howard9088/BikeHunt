"""Export BikeHunt's approved flat identity as sharp, self-contained PNG/ICO assets.

web/icons/bikehunt-logo.svg was traced from the user-selected bikeHUNT mark.
This publisher uses its companion bicycle/map-pin symbols for app and browser icons.
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
    """Regenerate the release PNGs/ICO from the approved SVG sources offline."""
    try:
        import cairosvg
    except ImportError as exc:
        raise RuntimeError("Install requirements-dev.txt to generate BikeHunt icons.") from exc
    directory = Path(directory)
    pngs = {}
    for size in sorted(set(PNG_OUTPUTS) | set(ICO_SIZES)):
        master = "favicon.svg" if size <= 48 else "bikehunt-app.svg"
        source = directory / master
        if not source.is_file():
            raise FileNotFoundError(f"Missing approved brand master: {source}")
        result = cairosvg.svg2png(url=str(source), output_width=size, output_height=size)
        if not result.startswith(b"\x89PNG\r\n\x1a\n") or struct.unpack(">II", result[16:24]) != (size, size):
            raise ValueError(f"Invalid BikeHunt icon at {size}px")
        pngs[size] = result
        if size in PNG_OUTPUTS:
            (directory / PNG_OUTPUTS[size]).write_bytes(result)

    entries = bytearray(struct.pack("<HHH", 0, 1, len(ICO_SIZES)))
    payload = bytearray()
    offset = 6 + len(ICO_SIZES) * 16
    for size in ICO_SIZES:
        data = pngs[size]
        entries.extend(struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(data), offset))
        payload.extend(data)
        offset += len(data)
    (directory / "favicon.ico").write_bytes(entries + payload)
