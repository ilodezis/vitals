"""Smaller copies of an uploaded photo, for the screens that show it.

A phone photo is 3–4 MB, and the diaries show it as a tile the size of a fingernail
or, opened, at screen size. Each progress or face photo gets two WebP copies next to
the original — a tile and a screen view — and the original stays exactly as it came.

The copies are derived data: deleting them loses nothing, and ``backfill`` makes any
missing ones again. They are named after the original (``uploads/ab12.jpeg`` →
``uploads/derived/ab12.jpeg.thumb.webp``), so the name alone leads from one to the
other and no column records them.

Paths here are ``file_key`` values — relative to the static directory, which the
caller passes in: the core does not know where the web layer keeps its files.
"""
from __future__ import annotations

import asyncio
import logging
import os
import posixpath
import tempfile
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.models.skincare import SkincarePhoto
from vitals.models.weight import ProgressPhoto

logger = logging.getLogger(__name__)

DERIVED_DIR = "derived"


@dataclass(frozen=True)
class Variant:
    name: str
    #: The longer side, in pixels; a smaller photo is never scaled up.
    size: int
    quality: int


# A tile is 96×124 CSS px: 480 covers it on a 3x phone screen. The opened photo is
# at most 760 CSS px wide, so 1600 stays sharp at 2x.
THUMB = Variant("thumb", 480, 76)
SCREEN = Variant("screen", 1600, 82)
VARIANTS = (THUMB, SCREEN)

_SUFFIXES = {f".{v.name}.webp": v for v in VARIANTS}


def derived_key(file_key: str, variant: Variant) -> str:
    folder, name = posixpath.split(file_key)
    return posixpath.join(folder, DERIVED_DIR, f"{name}.{variant.name}.webp")


def original_key(key: str) -> Optional[str]:
    """The photo a derived copy was made from, or ``None`` when ``key`` is not a copy."""
    folder, name = posixpath.split(key)
    if posixpath.basename(folder) != DERIVED_DIR:
        return None
    for suffix in _SUFFIXES:
        if name.endswith(suffix) and len(name) > len(suffix):
            return posixpath.join(posixpath.dirname(folder), name[: -len(suffix)])
    return None


def is_derived(key: str) -> bool:
    return original_key(key) is not None


def photo_urls(file_key: str) -> dict[str, str]:
    """The original's URL and its two copies'. A copy not made yet is still a valid
    URL: the server answers it with the original until it exists."""
    return {
        "url": f"/static/{file_key}",
        "thumb_url": f"/static/{derived_key(file_key, THUMB)}",
        "screen_url": f"/static/{derived_key(file_key, SCREEN)}",
    }


def _fit(size: tuple[int, int], longest: int) -> tuple[int, int]:
    w, h = size
    scale = min(1.0, longest / max(w, h))
    return max(1, round(w * scale)), max(1, round(h * scale))


def _write_webp(path: str, image: Image.Image, quality: int) -> None:
    # Written beside the target and renamed into place: a reader never sees half a file.
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".part")
    try:
        with os.fdopen(fd, "wb") as fh:
            image.save(fh, "WEBP", quality=quality, method=4)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def make_derivatives(static_dir: str, file_key: str) -> bool:
    """Write both copies of a photo. ``False`` when the original cannot be read as an
    image (a format the decoder does not know, a damaged file) — the original is kept
    either way, and the screens fall back to it.

    Blocking (decoding and encoding take a few hundred ms): run it in a thread.
    """
    source = os.path.join(static_dir, file_key)
    try:
        with Image.open(source) as opened:
            # A JPEG can decode straight at a fraction of its size — most of the cost
            # of a 12 MP photo is gone before a pixel is touched. Other formats ignore it.
            opened.draft("RGB", _fit(opened.size, SCREEN.size))
            # The camera stores the sensor's orientation in EXIF; the copies carry no
            # EXIF (and so no location either), so the rotation is baked in instead.
            image = ImageOps.exif_transpose(opened)
            has_alpha = image.mode in ("RGBA", "LA") or "transparency" in image.info
            image = image.convert("RGBA" if has_alpha else "RGB")
            for variant in sorted(VARIANTS, key=lambda v: -v.size):
                image.thumbnail((variant.size, variant.size), Image.Resampling.LANCZOS)
                _write_webp(os.path.join(static_dir, derived_key(file_key, variant)), image, variant.quality)
    except (OSError, ValueError, Image.DecompressionBombError):
        logger.warning("could not make the photo copies for %s", file_key, exc_info=True)
        return False
    return True


def remove_derivatives(static_dir: str, file_key: str) -> None:
    for variant in VARIANTS:
        path = os.path.join(static_dir, derived_key(file_key, variant))
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning("could not remove %s", path, exc_info=True)


def missing(static_dir: str, file_keys: Iterable[str]) -> list[str]:
    """The photos whose original is on disk but a copy is not."""
    return [
        key
        for key in file_keys
        if os.path.isfile(os.path.join(static_dir, key))
        and not all(os.path.isfile(os.path.join(static_dir, derived_key(key, v))) for v in VARIANTS)
    ]


async def photo_keys(session: AsyncSession) -> list[str]:
    """Every progress and face photo on record."""
    keys: list[str] = []
    for model in (ProgressPhoto, SkincarePhoto):
        keys.extend((await session.execute(select(model.file_key))).scalars().all())
    return keys


async def backfill(session_factory: Callable[[], AsyncSession], static_dir: str) -> int:
    """Make the copies every recorded photo is missing; returns how many photos got them.

    Run at startup, off the request path: it brings the photos from before the copies
    existed up to date, and repeats any that failed. A photo that cannot be decoded is
    tried again next time, which costs one failed open.
    """
    try:
        async with session_factory() as session:
            keys = await photo_keys(session)
        todo = await asyncio.to_thread(missing, static_dir, keys)
        made = 0
        for key in todo:
            if await asyncio.to_thread(make_derivatives, static_dir, key):
                made += 1
        if todo:
            logger.info("photo copies: made for %d of %d photos missing them", made, len(todo))
        return made
    except Exception:  # noqa: BLE001 — a startup chore; the screens fall back to the originals
        logger.warning("photo copy backfill failed", exc_info=True)
        return 0
