"""Modularity of the body-composition feature — it must be an optional module
that defaults off and behaves as if absent when disabled (data is hidden, not
deleted; that 'kept in DB' guarantee is covered by the service/delete tests)."""
from __future__ import annotations

from vitals.services import modules_service


def test_body_comp_registered_as_optional():
    spec = modules_service.MODULE_REGISTRY.get("body_comp")
    assert spec is not None
    assert spec.category == "optional"
    assert "body_comp" in modules_service.OPTIONAL_KEYS
    assert "body_comp" not in modules_service.CORE_KEYS
    # Safe default for an optional module is OFF.
    assert modules_service.DEFAULT_STATE["body_comp"] is False


async def test_get_enabled_modules_defaults_body_comp_off(db_session):
    # No app_settings row → safe defaults (core on, optional off).
    state = await modules_service.get_enabled_modules(db_session)
    assert state["body_comp"] is False
    assert state["weight"] is True


async def test_toggle_body_comp_on(db_session):
    state = await modules_service.set_module_enabled(db_session, key="body_comp", enabled=True)
    await db_session.commit()
    assert state["body_comp"] is True
    # Re-resolved from the DB.
    assert (await modules_service.get_enabled_modules(db_session))["body_comp"] is True
