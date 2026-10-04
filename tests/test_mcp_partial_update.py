"""MCP edit tools must not destroy the fields a call didn't mention.

The web forms post every field, so the update services replace wholesale — right
there, wrong for a tool call, which only carries what the conversation said. Before
this, ``update_meal(id, name=...)`` blanked the calories and moved the meal to
today; ``update_supplement(id, name=...)`` switched a paused supplement back on.

Also covers the data-overview domain map: a tool that claims to list "what data
exists" is worse than useless when it silently omits whole domains.
"""
from __future__ import annotations

import pytest

from vitals.enums import Domain

mcp_router = pytest.importorskip("web.routers.mcp")


@pytest.fixture(autouse=True)
def _use_test_factory(session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)


@pytest.fixture(autouse=True)
async def _optional_modules_on(session_factory):
    """Optional modules default to off, and the MCP write tools honour that
    (web/routers/mcp.gated). These tests write to optional domains — switch them on."""
    from vitals.services import modules_service

    async with session_factory() as session:
        for key in sorted(modules_service.OPTIONAL_KEYS):
            await modules_service.set_module_enabled(session, key=key, enabled=True)
        await session.commit()


# ── Partial updates ───────────────────────────────────────────────────────────
async def test_meal_rename_keeps_date_macros_and_note():
    created = await mcp_router.log_meal(
        name="Ужин", calories=700, protein_g=40, fat_g=20, carbs_g=60,
        note="дома", on_date="2026-07-01",
    )

    updated = await mcp_router.update_meal(created["id"], name="Ужин поздний")

    assert updated["name"] == "Ужин поздний"
    assert updated["date"] == "2026-07-01"
    assert updated["calories"] == 700
    assert (updated["protein_g"], updated["fat_g"], updated["carbs_g"]) == (40, 20, 60)
    assert updated["note"] == "дома"


async def test_glp1_edit_keeps_date_site_and_note():
    created = await mcp_router.log_glp1(
        drug="semaglutide", dose_mg=1.0, on_date="2026-07-01",
        site="abdomen_left", note="утро",
    )

    updated = await mcp_router.update_glp1(created["id"], dose_mg=2.0)

    assert updated["dose_mg"] == 2.0
    assert updated["drug"] == "semaglutide"
    assert updated["date"] == "2026-07-01"
    assert updated["site"] == "abdomen_left"
    assert updated["note"] == "утро"


async def test_supplement_rename_keeps_paused_state_and_fields():
    created = await mcp_router.add_supplement(name="Creatine", dose="5 g", evidence="A")
    sid = created["id"]
    assert (await mcp_router.set_supplement_active(sid, active=False))["active"] is False

    updated = await mcp_router.update_supplement(sid, name="Creatine Monohydrate")

    assert updated["name"] == "Creatine Monohydrate"
    assert updated["active"] is False
    assert updated["dose"] == "5 g"
    assert updated["evidence"] == "A"


async def test_partial_update_can_still_clear_by_passing_a_value():
    """Merging must not make a field un-editable — an explicit value still wins."""
    created = await mcp_router.log_meal(name="Обед", calories=500, on_date="2026-07-02")
    updated = await mcp_router.update_meal(created["id"], calories=650, on_date="2026-07-03")
    assert updated["calories"] == 650
    assert updated["date"] == "2026-07-03"
    assert updated["name"] == "Обед"


# ── Readable date errors ──────────────────────────────────────────────────────
async def test_bad_date_names_the_argument_and_the_shape():
    with pytest.raises(ValueError, match="on_date must be a YYYY-MM-DD date"):
        await mcp_router.log_meal(name="Ужин", on_date="вчера")

    with pytest.raises(ValueError, match="start_date must be a YYYY-MM-DD date"):
        await mcp_router.get_weight_logs(start_date="01.07.2026")

    with pytest.raises(ValueError, match="eaten_at must be an HH:MM time"):
        await mcp_router.log_meal(name="Ужин", eaten_at="вечером")


# ── The overview covers every domain ──────────────────────────────────────────
#
# Same guard as ``DOMAIN_EXPORT_KEYS`` in test_data_portability: the failure mode
# isn't a bug in the tool, it's a new domain nobody remembers to add — and a model
# that starts by orienting itself concludes the domain doesn't exist. Adding a
# Domain member without touching this map fails immediately.
DOMAIN_OVERVIEW_KEYS: dict[Domain, tuple[str, ...]] = {
    Domain.WEIGHT: ("weight", "measurements", "noise_markers"),
    Domain.BODY_COMPOSITION: ("body_scans",),
    Domain.GLP1: ("glp1_injections", "side_effects", "dose_phases"),
    Domain.HRT: ("hrt_doses", "hrt_side_effects", "hrt_cycles"),
    Domain.LABS: ("labs",),
    Domain.WORKOUTS: ("workouts",),
    Domain.GARMIN: ("garmin_daily", "garmin_activities", "garmin_intraday"),
    Domain.NUTRITION: ("nutrition",),
    Domain.SUPPLEMENTS: ("supplements",),
    Domain.GENETICS: ("genetics",),
    Domain.SKINCARE: ("skincare_logs", "skincare_observations"),
    Domain.MILESTONES: ("milestones", "weekly_digests"),
    Domain.TIMELINE: ("timeline",),
    Domain.SIGNALS: ("signals", "day_context"),
    Domain.ENVIRONMENT: ("environment_samples", "environment_hourly"),
    # Alerts are infra, not a data domain to orient in — deliberately absent.
    Domain.SYSTEM: (),
}


def test_every_domain_is_mapped_to_overview_keys():
    assert set(DOMAIN_OVERVIEW_KEYS) == set(Domain)


async def test_overview_reports_every_mapped_key():
    overview = await mcp_router.get_data_overview()
    expected = {k for keys in DOMAIN_OVERVIEW_KEYS.values() for k in keys}
    assert expected <= set(overview)


async def test_overview_counts_the_domains_it_used_to_hide():
    await mcp_router.set_module("signals", True)
    await mcp_router.log_signal(key="headache", kind="symptom", on_date="2026-07-01")
    await mcp_router.log_hrt_dose(
        compound_key="testosterone_enanthate", dose=100, unit="mg", on_date="2026-07-01"
    )

    overview = await mcp_router.get_data_overview()

    assert overview["signals"]["count"] == 1
    assert overview["signals"]["latest"] == "2026-07-01"
    assert overview["hrt_doses"]["count"] == 1
