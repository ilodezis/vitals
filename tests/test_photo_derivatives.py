"""The tile and screen copies of progress and face photos, and how photos are served."""
from __future__ import annotations

import io
import os
import uuid

import pytest
from PIL import Image

from vitals.models.skincare import SkincarePhoto
from vitals.models.weight import ProgressPhoto
from vitals.services import modules_service, photo_derivatives
from vitals.services.photo_derivatives import SCREEN, THUMB, derived_key, original_key
from web.templating import STATIC_DIR

API = "/api/v1"


def _jpeg(size=(4000, 3000), orientation: int | None = None) -> bytes:
    image = Image.new("RGB", size, (200, 150, 120))
    buf = io.BytesIO()
    exif = Image.Exif()
    if orientation is not None:
        exif[0x0112] = orientation
    exif[0x010F] = "PhoneMaker"
    image.save(buf, "JPEG", exif=exif, quality=80)
    return buf.getvalue()


def _png_with_alpha() -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (800, 600), (10, 20, 30, 128)).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def static_dir(tmp_path):
    (tmp_path / "uploads").mkdir()
    return str(tmp_path)


def _put(static_dir: str, data: bytes, ext: str = ".jpeg") -> str:
    key = f"uploads/{uuid.uuid4().hex}{ext}"
    with open(os.path.join(static_dir, key), "wb") as fh:
        fh.write(data)
    return key


def _open(static_dir: str, key: str) -> Image.Image:
    return Image.open(os.path.join(static_dir, key))


# ── Names ─────────────────────────────────────────────────────────────────────


def test_a_copy_is_named_after_its_original_and_leads_back_to_it():
    key = "uploads/ab12.jpeg"
    assert derived_key(key, THUMB) == "uploads/derived/ab12.jpeg.thumb.webp"
    assert derived_key(key, SCREEN) == "uploads/derived/ab12.jpeg.screen.webp"
    assert original_key(derived_key(key, THUMB)) == key
    # Relative to the uploads folder, as the serving route sees it.
    assert original_key("derived/ab12.jpeg.screen.webp") == "ab12.jpeg"


def test_anything_else_is_not_a_copy():
    for key in ("ab12.jpeg", "labs/ab12.pdf", "derived/ab12.jpeg", "derived/.thumb.webp", "other/ab.jpeg.thumb.webp"):
        assert original_key(key) is None, key


def test_the_urls_name_the_original_and_both_copies():
    assert photo_derivatives.photo_urls("uploads/ab12.jpeg") == {
        "url": "/static/uploads/ab12.jpeg",
        "thumb_url": "/static/uploads/derived/ab12.jpeg.thumb.webp",
        "screen_url": "/static/uploads/derived/ab12.jpeg.screen.webp",
    }


# ── Making them ───────────────────────────────────────────────────────────────


def test_a_phone_photo_gets_a_tile_and_a_screen_copy(static_dir):
    key = _put(static_dir, _jpeg())
    original = open(os.path.join(static_dir, key), "rb").read()

    assert photo_derivatives.make_derivatives(static_dir, key) is True

    screen = _open(static_dir, derived_key(key, SCREEN))
    thumb = _open(static_dir, derived_key(key, THUMB))
    assert (screen.format, screen.size) == ("WEBP", (1600, 1200))
    assert (thumb.format, thumb.size) == ("WEBP", (480, 360))
    # The original is left exactly as it came.
    assert open(os.path.join(static_dir, key), "rb").read() == original


def test_the_camera_rotation_is_baked_in_and_exif_is_dropped(static_dir):
    # Orientation 6: stored landscape, shown rotated 90° — a portrait shot.
    key = _put(static_dir, _jpeg(orientation=6))
    assert photo_derivatives.make_derivatives(static_dir, key)

    screen = _open(static_dir, derived_key(key, SCREEN))
    assert screen.size == (1200, 1600)
    assert len(screen.getexif()) == 0


def test_a_small_photo_is_not_scaled_up(static_dir):
    key = _put(static_dir, _jpeg(size=(640, 480)))
    assert photo_derivatives.make_derivatives(static_dir, key)
    assert _open(static_dir, derived_key(key, SCREEN)).size == (640, 480)
    assert _open(static_dir, derived_key(key, THUMB)).size == (480, 360)


def test_transparency_survives(static_dir):
    key = _put(static_dir, _png_with_alpha(), ".png")
    assert photo_derivatives.make_derivatives(static_dir, key)
    assert _open(static_dir, derived_key(key, THUMB)).mode == "RGBA"


def test_a_file_that_is_not_an_image_gets_no_copies(static_dir):
    key = _put(static_dir, b"not really a jpeg")
    assert photo_derivatives.make_derivatives(static_dir, key) is False
    assert photo_derivatives.missing(static_dir, [key]) == [key]
    assert not os.path.exists(os.path.join(static_dir, "uploads", "derived")) or not os.listdir(
        os.path.join(static_dir, "uploads", "derived")
    )


def test_missing_lists_only_photos_on_disk_without_both_copies(static_dir):
    done = _put(static_dir, _jpeg(size=(800, 600)))
    photo_derivatives.make_derivatives(static_dir, done)
    half = _put(static_dir, _jpeg(size=(800, 600)))
    photo_derivatives.make_derivatives(static_dir, half)
    os.remove(os.path.join(static_dir, derived_key(half, THUMB)))
    fresh = _put(static_dir, _jpeg(size=(800, 600)))

    assert photo_derivatives.missing(static_dir, [done, half, fresh, "uploads/gone.jpeg"]) == [half, fresh]


def test_removing_the_copies_leaves_the_original(static_dir):
    key = _put(static_dir, _jpeg(size=(800, 600)))
    photo_derivatives.make_derivatives(static_dir, key)
    photo_derivatives.remove_derivatives(static_dir, key)
    photo_derivatives.remove_derivatives(static_dir, key)  # a second time is a no-op
    assert os.path.isfile(os.path.join(static_dir, key))
    assert photo_derivatives.missing(static_dir, [key]) == [key]


# ── The startup backfill ──────────────────────────────────────────────────────


async def test_backfill_makes_the_copies_older_photos_lack(db_session, session_factory, static_dir):
    import datetime as dt

    old_progress = _put(static_dir, _jpeg(size=(800, 600)))
    old_face = _put(static_dir, _jpeg(size=(800, 600)))
    broken = _put(static_dir, b"garbage")
    day = dt.date(2026, 10, 1)
    db_session.add_all(
        [
            ProgressPhoto(date=day, domain="weight", source="manual", file_key=old_progress),
            SkincarePhoto(date=day, domain="skincare", source="manual", file_key=old_face),
            SkincarePhoto(date=day, domain="skincare", source="manual", file_key=broken),
        ]
    )
    await db_session.commit()

    assert await photo_derivatives.backfill(session_factory, static_dir) == 2
    assert photo_derivatives.missing(static_dir, [old_progress, old_face]) == []
    # Nothing left but the photo it could not read — and a second run makes nothing new.
    assert await photo_derivatives.backfill(session_factory, static_dir) == 0


# ── Upload, delete, serve ─────────────────────────────────────────────────────


def _cleanup(file_key: str) -> None:
    for key in (file_key, derived_key(file_key, THUMB), derived_key(file_key, SCREEN)):
        path = os.path.join(STATIC_DIR, key)
        if os.path.exists(path):
            os.remove(path)


async def test_an_uploaded_face_photo_gets_its_copies_and_loses_them_on_delete(auth_client, db_session):
    await modules_service.set_module_enabled(db_session, key="skincare", enabled=True)
    await db_session.commit()
    response = await auth_client.post(
        f"{API}/skincare/photos",
        files={"files": ("face.jpg", _jpeg(), "image/jpeg")},
        data={"date": "2026-10-20"},
    )
    assert response.status_code == 201
    item = response.json()[0]
    file_key = item["url"].removeprefix("/static/")
    try:
        assert item["thumbUrl"] == f"/static/{derived_key(file_key, THUMB)}"
        assert item["screenUrl"] == f"/static/{derived_key(file_key, SCREEN)}"
        assert photo_derivatives.missing(STATIC_DIR, [file_key]) == []

        view = (await auth_client.get(f"{API}/skincare")).json()
        assert view["photos"][0]["thumbUrl"] == item["thumbUrl"]

        assert (await auth_client.delete(f"{API}/skincare/photos/{item['id']}")).status_code == 204
        for key in (file_key, derived_key(file_key, THUMB), derived_key(file_key, SCREEN)):
            assert not os.path.exists(os.path.join(STATIC_DIR, key)), key
    finally:
        _cleanup(file_key)


async def test_an_uploaded_progress_photo_gets_its_copies(auth_client, db_session):
    response = await auth_client.post(
        f"{API}/weight/photos",
        files={"file": ("progress.jpg", _jpeg(), "image/jpeg")},
        data={"date": "2026-10-20"},
    )
    assert response.status_code == 201
    item = response.json()[0]
    try:
        assert item["thumb_url"] == f"/static/{derived_key(item['file_key'], THUMB)}"
        assert photo_derivatives.missing(STATIC_DIR, [item["file_key"]]) == []
        assert (await auth_client.delete(f"{API}/weight/photos/{item['id']}")).status_code == 204
        assert not os.path.exists(os.path.join(STATIC_DIR, derived_key(item["file_key"], SCREEN)))
    finally:
        _cleanup(item["file_key"])


async def test_a_photo_that_cannot_be_decoded_is_still_saved(auth_client, db_session):
    response = await auth_client.post(
        f"{API}/weight/photos",
        files={"file": ("progress.jpg", b"fake-jpeg-image-bytes", "image/jpeg")},
        data={"date": "2026-10-20"},
    )
    assert response.status_code == 201
    item = response.json()[0]
    try:
        assert os.path.isfile(os.path.join(STATIC_DIR, item["file_key"]))
        # Its copy's URL answers with the original, uncached.
        r = await auth_client.get(item["thumb_url"])
        assert r.status_code == 200
        assert r.content == b"fake-jpeg-image-bytes"
        assert "no-store" in r.headers["cache-control"]
    finally:
        _cleanup(item["file_key"])


async def test_photos_and_their_copies_are_kept_by_the_browser(auth_client):
    file_key = f"uploads/{uuid.uuid4().hex}.jpeg"
    with open(os.path.join(STATIC_DIR, file_key), "wb") as fh:
        fh.write(_jpeg(size=(800, 600)))
    photo_derivatives.make_derivatives(STATIC_DIR, file_key)
    try:
        for key in (file_key, derived_key(file_key, THUMB), derived_key(file_key, SCREEN)):
            r = await auth_client.get(f"/static/{key}")
            assert r.status_code == 200, key
            cache = r.headers["cache-control"]
            # Kept by this browser only: never by Cloudflare or any shared cache.
            assert "private" in cache and "immutable" in cache and "no-store" not in cache, key
    finally:
        _cleanup(file_key)


async def test_documents_outside_the_photo_folder_stay_uncached(auth_client):
    labs = os.path.join(STATIC_DIR, "uploads", "labs")
    os.makedirs(labs, exist_ok=True)
    name = f"{uuid.uuid4().hex}.jpg"
    path = os.path.join(labs, name)
    with open(path, "wb") as fh:
        fh.write(b"lab sheet photo")
    try:
        r = await auth_client.get(f"/static/uploads/labs/{name}")
        assert r.status_code == 200
        assert "no-store" in r.headers["cache-control"]
    finally:
        os.remove(path)


async def test_a_copy_of_nothing_is_a_miss(auth_client):
    r = await auth_client.get("/static/uploads/derived/nothing.jpeg.thumb.webp")
    assert r.status_code == 404


async def test_a_copy_is_not_public(client):
    r = await client.get("/static/uploads/derived/anything.jpeg.thumb.webp")
    assert r.status_code == 401
