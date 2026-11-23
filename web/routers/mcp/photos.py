"""The face and progress photo galleries."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Optional

from sqlalchemy import select

from vitals.models import (
    ProgressPhoto, SkincarePhoto,
)
from vitals.services import photo_derivatives
from vitals.utils.timeutils import today_local
from web.routers.mcp._core import (
    READ, WRITE, _module_enabled,
    _parse_date, get_session_factory, logger,
    route, serialize_row, tool,
)

# ── Photos: the weight's progress photos and the face diary ──────────────────
# Two galleries with one shape (a dated row + a file under static/uploads), so
# one set of tools serves both. ``get_photo`` hands the picture itself back as
# image content, scaled down: the model can look at it and compare, which a URL
# behind the owner's login never allowed.
_PHOTO_KINDS = ("face", "progress")
PHOTO_MAX_BYTES = 25 * 1024 * 1024  # the app's upload cap
PHOTOS_PER_LIST_MAX = 200
_PHOTO_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}


def _photo_model(kind: str):

    return SkincarePhoto if kind == "face" else ProgressPhoto


async def _photo_kind_error(session, kind: str) -> Optional[dict]:
    """``None`` when ``kind`` is usable; the face diary belongs to skincare."""
    if kind not in _PHOTO_KINDS:
        return {"error": f"kind must be one of {', '.join(_PHOTO_KINDS)}"}
    if kind == "face" and not await _module_enabled(session, "skincare"):
        return {"error": "module 'skincare' is disabled"}
    return None


def _photo_row(row) -> dict:
    d = serialize_row(row)
    d.update(photo_derivatives.photo_urls(row.file_key))
    return d


async def list_photos(
    kind: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """Lists photos from one of the app's two galleries, newest first:
    ``kind="face"`` — the face photo diary on the skincare screen;
    ``kind="progress"`` — the body progress photos on the weight screen.
    Each row is ``{id, date, note, url}`` (the url is a path behind the owner's
    login — to actually look at a photo call ``get_photo``). Optional
    YYYY-MM-DD range; most recent 50 by default. READ tool."""
    session_factory = get_session_factory()
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")
    async with session_factory() as session:
        problem = await _photo_kind_error(session, kind)
        if problem:
            return [problem]
        model = _photo_model(kind)
        stmt = select(model)
        if start:
            stmt = stmt.where(model.date >= start)
        if end:
            stmt = stmt.where(model.date <= end)
        stmt = stmt.order_by(model.date.desc(), model.id.desc()).limit(
            max(1, min(limit, PHOTOS_PER_LIST_MAX))
        )
        return [_photo_row(r) for r in (await session.execute(stmt)).scalars().all()]


def _scaled_jpeg(path: str, max_px: int) -> bytes:
    """The stored photo, upright (EXIF orientation applied) and fitted inside
    ``max_px`` on its longer side, as a JPEG."""
    import io

    from PIL import Image as PilImage, ImageOps

    with PilImage.open(path) as img:
        img = ImageOps.exif_transpose(img)
        img.thumbnail((max_px, max_px))
        out = io.BytesIO()
        img.convert("RGB").save(out, "JPEG", quality=85)
        return out.getvalue()


async def get_photo(kind: str, photo_id: int, max_px: int = 1024):
    """Shows one photo — returns its details and the image itself, so you can
    look at it: compare the face week to week (inflammation, marks, redness) or
    the body against an earlier progress photo. ``kind`` is "face" or
    "progress", ``photo_id`` from ``list_photos``. ``max_px`` bounds the longer
    side (default 1024, 256–2048): larger shows more detail but costs more of the
    conversation — ask for one or two photos at a time, not a whole gallery.
    READ tool."""
    import asyncio

    from fastmcp.tools import ToolResult
    from fastmcp.utilities.types import Image
    from mcp.types import TextContent

    from web.templating import STATIC_DIR

    session_factory = get_session_factory()
    async with session_factory() as session:
        problem = await _photo_kind_error(session, kind)
        if problem:
            return problem
        row = await session.get(_photo_model(kind), photo_id)
        if row is None:
            return {"error": f"{kind} photo {photo_id} not found"}
        meta = _photo_row(row)

    path = os.path.join(STATIC_DIR, row.file_key)
    if not os.path.exists(path):
        return {**meta, "error": "the file is missing on disk"}
    try:
        data = await asyncio.to_thread(_scaled_jpeg, path, max(256, min(int(max_px), 2048)))
    except Exception:  # noqa: BLE001 — HEIC without a decoder, a truncated file…
        logger.warning("mcp: cannot render photo %s", row.file_key, exc_info=True)
        return {**meta, "error": "this file can't be rendered here (unsupported or damaged image)"}
    return ToolResult(content=[
        TextContent(type="text", text=json.dumps(meta, ensure_ascii=False)),
        Image(data=data, format="jpeg").to_image_content(),
    ])


def _decode_image(image_base64: str) -> tuple[bytes, str]:
    """Base64 (optionally a ``data:`` URL) → ``(bytes, extension)``. The bytes are
    checked to be a JPEG, PNG or WebP image — whatever the caller claims."""
    import base64
    import binascii
    import io

    from PIL import Image as PilImage, UnidentifiedImageError

    raw = (image_base64 or "").strip()
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    if len(raw) * 3 // 4 > PHOTO_MAX_BYTES:
        raise ValueError(f"image too large (max {PHOTO_MAX_BYTES // (1024 * 1024)} MB)")
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("image_base64 is not valid base64") from None
    try:
        with PilImage.open(io.BytesIO(data)) as img:
            fmt = img.format
            img.verify()
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise ValueError("image_base64 does not decode to an image") from None
    ext = _PHOTO_FORMATS.get(fmt or "")
    if ext is None:
        raise ValueError(f"unsupported image format {fmt} — send JPEG, PNG or WebP")
    return data, ext


@tool(WRITE)
async def add_photo(
    kind: str,
    image_base64: str,
    on_date: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Adds a photo to a gallery — ``kind="face"`` (the skincare face diary) or
    ``kind="progress"`` (body progress photos on the weight screen) — dated
    ``on_date`` (default today), with an optional note.

    ``image_base64`` is the file's bytes in base64 (a ``data:image/...;base64,``
    prefix is fine): JPEG, PNG or WebP, up to 25 MB. This only works where you
    actually hold the file's bytes (e.g. a client with file access). A photo the
    owner attached to a chat message is NOT available to you as bytes — don't
    try to re-create or describe it into this tool; ask the owner to upload it in
    the app instead. WRITE tool — saved immediately."""
    import uuid

    from vitals.services import skincare_service, weight_service
    from web.templating import STATIC_DIR
    from web.uploads import write_upload

    try:
        data, ext = _decode_image(image_base64)
    except ValueError as e:
        return {"error": str(e)}
    parsed_date = _parse_date(on_date, today_local(), field="on_date")
    note = (note or "").strip() or None

    session_factory = get_session_factory()
    async with session_factory() as session:
        problem = await _photo_kind_error(session, kind)
        if problem:
            return problem
        file_key = f"uploads/{uuid.uuid4().hex}{ext}"
        await write_upload(os.path.join(STATIC_DIR, file_key), data)
        # The same tile and screen copies an upload from the app gets.
        await asyncio.to_thread(photo_derivatives.make_derivatives, STATIC_DIR, file_key)
        add = skincare_service.add_photo if kind == "face" else weight_service.add_progress_photo
        row = await add(session, on_date=parsed_date, file_key=file_key, note=note)
        await session.commit()
        await session.refresh(row)
        return _photo_row(row)


# ── Consolidated read tool ───────────────────────────────────────────────────
@tool(READ)
async def get_photos(
    kind: str,
    photo_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: Optional[int] = None,
    max_px: Optional[int] = None,
):
    """The app's two photo galleries: ``kind="face"`` (the skincare face diary)
    or ``kind="progress"`` (body progress photos on the weight screen).

    Without ``photo_id``: ``{"photos": [...]}``, newest first — ``{id, date,
    note, url}`` per photo (the url sits behind the owner's login), optional
    YYYY-MM-DD range, ``limit`` default 50. With ``photo_id``: that photo's
    details and the image itself, so you can look at it (compare the face week
    to week, the body against an earlier photo). ``max_px`` bounds the longer
    side (default 1024, 256–2048) — ask for one or two photos at a time, not a
    whole gallery."""
    if photo_id is not None:
        return await route(
            get_photo, "get_photos(photo_id)",
            dict(kind=kind, photo_id=photo_id, max_px=max_px, start_date=start_date,
                 end_date=end_date, limit=limit),
        )
    rows = await route(
        list_photos, "get_photos",
        dict(kind=kind, start_date=start_date, end_date=end_date, limit=limit, max_px=max_px),
    )
    return rows if isinstance(rows, dict) else {"photos": rows}
