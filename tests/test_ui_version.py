"""Regression tests for the single canonical Vitals application shell."""
from __future__ import annotations

from datetime import date

import pytest

from vitals.models.garmin import GarminDaily

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("path", ("/weight", "/garmin", "/timeline", "/settings"))
async def test_authenticated_pages_render_one_vitals_shell(auth_client, path):
    response = await auth_client.get(path, headers={"Accept": "text/html"})

    assert response.status_code == 200
    assert "ui-vitals" in response.text
    assert 'id="main-content"' in response.text
    assert 'id="vitals-navigation"' in response.text
    assert 'id="primary-nav"' not in response.text
    assert 'id="primary-nav-masthead"' not in response.text


async def test_missing_page_uses_the_same_vitals_shell(auth_client):
    response = await auth_client.get(
        "/this-page-does-not-exist",
        headers={"Accept": "text/html"},
    )

    assert response.status_code == 404
    assert "ui-vitals" in response.text
    assert 'id="main-content"' in response.text
    assert 'id="vitals-navigation"' in response.text


async def test_settings_has_no_interface_version_switch(auth_client):
    response = await auth_client.get("/settings", headers={"Accept": "text/html"})

    assert response.status_code == 200
    assert "/settings/ui-version" not in response.text
    assert 'name="ui_version"' not in response.text

    removed_route = await auth_client.post(
        "/settings/ui-version",
        data={"ui_version": "classic"},
    )
    assert removed_route.status_code == 404


async def test_masthead_rubric_number_is_stable_per_rubric(auth_client, db_session):
    """The rubric number follows the rubric, not the active tab inside it."""
    db_session.add(
        GarminDaily(
            date=date(2026, 6, 10),
            domain="garmin",
            source="garmin_api",
            sleep_seconds=27000,
        )
    )
    await db_session.commit()

    for path in (
        "/weight",
        "/garmin",
        "/garmin/sleep",
        "/garmin/sleep/2026-06-10",
        "/garmin/activities",
        "/reports",
    ):
        response = await auth_client.get(path, headers={"Accept": "text/html"})
        assert response.status_code == 200
        assert "Раздел 01 ·" in response.text

    response = await auth_client.get("/genetics", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "Раздел 02 · Маркеры" in response.text

    response = await auth_client.get("/supplements", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "Раздел 03 · Образ жизни" in response.text


async def test_consistent_layout_max_width(auth_client):
    """Each page family keeps its sanctioned shared outer-width wrapper.

    Pages migrated to a scoped Quiet Precision layer (data/context/settings)
    own their width there; anything else must still use the legacy Tailwind
    wrapper so no page renders edge-to-edge.
    """
    sanctioned = {
        "/weight": "v-data-page",
        "/timeline": "v-context-page",
        "/settings": "settings-page",
    }
    for path, wrapper in sanctioned.items():
        response = await auth_client.get(path, headers={"Accept": "text/html"})
        assert response.status_code == 200
        assert wrapper in response.text, path
