"""Tests for ``/api/v1/nutrition`` — nutrition dashboard, KBJU tracking,
and meal logging CRUD.
"""
from __future__ import annotations

import datetime as dt

import pytest

from vitals.services import modules_service
from vitals.utils.timeutils import today_local

NUTRITION = "/api/v1/nutrition"


async def _set_module(db_session, redis, key: str, enabled: bool):
    state = await modules_service.set_module_enabled(db_session, key=key, enabled=enabled)
    await db_session.commit()
    await modules_service.prime_cache(redis, state)


async def test_nutrition_guarded(client):
    r = await client.get(NUTRITION)
    assert r.status_code == 401
    assert r.json() == {"error": "unauthenticated"}

    r_post = await client.post(f"{NUTRITION}/meals", json={"date": "2026-03-15", "name": "Lunch"})
    assert r_post.status_code == 401
    assert r_post.json() == {"error": "unauthenticated"}


async def test_nutrition_disabled_module_gives_404(auth_client, db_session, redis):
    await _set_module(db_session, redis, "nutrition", False)
    r = await auth_client.get(NUTRITION)
    assert r.status_code == 404
    assert r.json() == {"error": "module_disabled"}


async def test_nutrition_empty_view(auth_client, db_session, redis):
    await _set_module(db_session, redis, "nutrition", True)
    r = await auth_client.get(NUTRITION)
    assert r.status_code == 200
    data = r.json()
    assert set(data) == {
        "date", "today_date", "is_today", "prev_date", "next_date",
        "totals", "goals", "calories_pct", "protein_pct", "macro_split",
        "meals", "recent_days",
    }  # fmt: skip
    assert data["totals"]["calories"] == 0.0
    assert data["meals"] == []
    assert data["goals"]["calories_max"] > 0


async def test_meal_crud_flow(auth_client, db_session, redis):
    await _set_module(db_session, redis, "nutrition", True)
    today = today_local().isoformat()

    # 1. Create a meal
    create_payload = {
        "date": today,
        "time": "12:30",
        "name": "Chicken Breast with Rice",
        "calories": 650.0,
        "protein_g": 55.0,
        "fat_g": 12.0,
        "carbs_g": 75.0,
        "note": "Post-workout meal",
    }
    r_create = await auth_client.post(f"{NUTRITION}/meals", json=create_payload)
    assert r_create.status_code == 201
    meal_id = r_create.json()["id"]
    assert isinstance(meal_id, int)

    # 2. Check it appears on dashboard
    r_view = await auth_client.get(f"{NUTRITION}?date={today}")
    assert r_view.status_code == 200
    data = r_view.json()
    assert data["totals"]["calories"] == 650.0
    assert data["totals"]["protein_g"] == 55.0
    assert len(data["meals"]) == 1
    assert data["meals"][0]["name"] == "Chicken Breast with Rice"
    assert data["meals"][0]["time"] == "12:30"
    assert data["calories_pct"] > 0

    # 3. Patch the meal
    patch_payload = {
        "calories": 700.0,
        "carbs_g": 85.0,
        "note": "Extra portion of rice",
    }
    r_patch = await auth_client.patch(f"{NUTRITION}/meals/{meal_id}", json=patch_payload)
    assert r_patch.status_code == 200
    assert r_patch.json()["id"] == meal_id

    # Verify update
    r_view2 = await auth_client.get(f"{NUTRITION}?date={today}")
    assert r_view2.status_code == 200
    assert r_view2.json()["totals"]["calories"] == 700.0
    assert r_view2.json()["meals"][0]["note"] == "Extra portion of rice"

    # 4. Patch non-existent meal -> 404
    r_patch_missing = await auth_client.patch(f"{NUTRITION}/meals/999999", json={"calories": 100})
    assert r_patch_missing.status_code == 404
    assert r_patch_missing.json() == {"error": "not_found"}

    # 5. Delete meal
    r_del = await auth_client.delete(f"{NUTRITION}/meals/{meal_id}")
    assert r_del.status_code == 204

    # 6. Delete already deleted meal -> 404
    r_del2 = await auth_client.delete(f"{NUTRITION}/meals/{meal_id}")
    assert r_del2.status_code == 404
    assert r_del2.json() == {"error": "not_found"}

    # 7. Check meals empty again
    r_view3 = await auth_client.get(f"{NUTRITION}?date={today}")
    assert r_view3.status_code == 200
    assert r_view3.json()["totals"]["calories"] == 0.0
    assert len(r_view3.json()["meals"]) == 0
