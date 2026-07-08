#!/usr/bin/env python3
"""Generate a maskable PWA icon with a safe-zone margin from icon-512.png.

Android (and other platforms honouring the "maskable" icon purpose) crops the
whole 512x512 image to an arbitrary shape (circle, squircle, ...) chosen by the
OS. icon-512.png is sized for the "any" purpose — its logo mark fills most of
the canvas — so used as-is for "maskable" it gets clipped. This scales the
existing icon down to ~64% width (~18% padding per side, comfortably inside
the ~80%-diameter safe zone platforms recommend) and centers it on a solid
brand-color (#1D1A21) background. icon-512.png's own background already
matches that color, so the seam between the shrunk icon and the new canvas is
invisible.

Usage:
    python -m scripts.make_maskable_icon
"""
from __future__ import annotations

import pathlib

from PIL import Image

_ICONS_DIR = pathlib.Path(__file__).resolve().parent.parent / "web" / "static" / "icons"
_SOURCE = _ICONS_DIR / "icon-512.png"
_OUTPUT = _ICONS_DIR / "icon-512-maskable.png"
_CANVAS_SIZE = 512
_SAFE_ZONE_SCALE = 0.64  # logo mark width as a fraction of the canvas
_BRAND_BG = (0x1D, 0x1A, 0x21)
# icon-512.png's own rounded-square edge has a 1-2px antialiasing halo baked
# in (its corners were composited against some other background before being
# exported with transparency). Flattening onto our matching brand background
# doesn't remove that halo, and resizing would smear it further, so trim it
# off before scaling down rather than trying to filter it out after.
_EDGE_TRIM = 6


def main() -> None:
    source = Image.open(_SOURCE).convert("RGBA")

    # Flatten onto an opaque brand-color canvas first (source and target
    # backgrounds match exactly, so this is invisible) — resizing is then
    # working with a fully opaque image, with no alpha channel left to cause
    # fringing at the transparent-corner boundary.
    flattened = Image.new("RGBA", source.size, (*_BRAND_BG, 255))
    flattened.alpha_composite(source)
    flattened = flattened.convert("RGB")

    w, h = flattened.size
    trimmed = flattened.crop((_EDGE_TRIM, _EDGE_TRIM, w - _EDGE_TRIM, h - _EDGE_TRIM))

    scaled_size = round(_CANVAS_SIZE * _SAFE_ZONE_SCALE)
    scaled = trimmed.resize((scaled_size, scaled_size), Image.LANCZOS)

    canvas = Image.new("RGB", (_CANVAS_SIZE, _CANVAS_SIZE), _BRAND_BG)
    offset = (_CANVAS_SIZE - scaled_size) // 2
    canvas.paste(scaled, (offset, offset))

    canvas.save(_OUTPUT)
    print(
        f"Wrote {_OUTPUT} ({_CANVAS_SIZE}x{_CANVAS_SIZE}, logo at "
        f"{_SAFE_ZONE_SCALE:.0%} width, {offset}px margin per side)."
    )


if __name__ == "__main__":
    main()
