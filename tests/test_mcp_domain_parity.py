"""The domains Claude could only ever half-use.

Genetics was readable a hundred alphabetical rows at a time, so "посмотри мой
rs1801133" was unanswerable and a fresh interpretation had nowhere to go. HRT
could be written but never corrected: no edit, no delete, no side effect, no way
to close a finished cycle — the parity GLP-1 has had all along.

Same import-skip guard as the other MCP tool tests; all on the fast SQLite path.
"""
from __future__ import annotations

import pytest

mcp_router = pytest.importorskip("web.routers.mcp")


@pytest.fixture(autouse=True)
def _use_test_factory(session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)


@pytest.fixture(autouse=True)
async def _optional_modules_on(session_factory):
    from vitals.services import modules_service

    async with session_factory() as session:
        for key in sorted(modules_service.OPTIONAL_KEYS):
            await modules_service.set_module_enabled(session, key=key, enabled=True)
        await session.commit()


# ── genetics ──────────────────────────────────────────────────────────────────
async def test_genetics_filters_by_gene_and_rsid():
    await mcp_router.upsert_genetic_variant(gene="MTHFR", rsid="rs1801133", genotype="CT")
    await mcp_router.upsert_genetic_variant(gene="COMT", rsid="rs4680", genotype="AA")

    assert [v["rsid"] for v in await mcp_router.get_genetics_snps(rsid="rs1801133")] == [
        "rs1801133"
    ]
    # The model writes the gene the way a person says it; the filter shouldn't care.
    assert [v["gene"] for v in await mcp_router.get_genetics_snps(gene="comt")] == ["COMT"]
    assert await mcp_router.get_genetics_snps(rsid="rs000000") == []
    assert len(await mcp_router.get_genetics_snps()) == 2


async def test_upsert_variant_edits_instead_of_duplicating_and_keeps_the_genotype():
    first = await mcp_router.upsert_genetic_variant(
        gene="MTHFR", rsid="rs1801133", genotype="TT", marker="mthfr_c677t_tt"
    )

    # A second call about the same rsid carrying only an interpretation must not
    # blank the genotype an import wrote, nor create a second row.
    second = await mcp_router.upsert_genetic_variant(
        gene="MTHFR", rsid="rs1801133", interpretation="сниженная активность фермента"
    )
    assert second["id"] == first["id"]
    assert second["genotype"] == "TT"
    assert second["marker"] == "mthfr_c677t_tt"
    assert second["interpretation"] == "сниженная активность фермента"
    assert len(await mcp_router.get_genetics_snps()) == 1


async def test_delete_genetic_variant():
    row = await mcp_router.upsert_genetic_variant(gene="COMT", rsid="rs4680", genotype="AA")
    assert await mcp_router.delete_record("genetics", row["id"], confirm=True) == {
        "deleted": True,
        "domain": "genetics",
        "record_id": row["id"],
    }
    assert await mcp_router.get_genetics_snps() == []


# ── HRT parity ────────────────────────────────────────────────────────────────
async def test_update_hrt_dose_keeps_the_fields_the_call_left_out():
    created = await mcp_router.log_hrt_dose(
        compound_key="testosterone_enanthate",
        dose=250.0,
        on_date="2026-07-01",
        site="glute_left",
        note="первая после перерыва",
    )

    # A correction of the amount alone — the date, the site and the note stay.
    updated = await mcp_router.update_hrt_dose(created["id"], dose=200.0)
    assert updated["dose"] == 200.0
    assert updated["date"] == "2026-07-01"
    assert updated["site"] == "glute_left"
    assert updated["note"] == "первая после перерыва"
    assert updated["compound_key"] == "testosterone_enanthate"

    assert "error" in await mcp_router.update_hrt_dose(9999, dose=1.0)


async def test_update_hrt_dose_recomputes_mg_from_a_new_volume():
    created = await mcp_router.log_hrt_dose(
        compound_key="testosterone_enanthate", dose=250.0, on_date="2026-07-01"
    )
    updated = await mcp_router.update_hrt_dose(
        created["id"], volume_ml=0.5, concentration_mg_ml=250.0
    )
    assert updated["dose"] == 125.0


async def test_delete_hrt_dose():
    created = await mcp_router.log_hrt_dose(
        compound_key="testosterone_enanthate", dose=250.0, on_date="2026-07-01"
    )
    assert await mcp_router.delete_record("hrt_dose", created["id"], confirm=True) == {
        "deleted": True,
        "domain": "hrt_dose",
        "record_id": created["id"],
    }
    assert (await mcp_router.get_hrt_logs())["doses"] == []


async def test_log_hrt_side_effect_is_its_own_domain():
    row = await mcp_router.log_hrt_side_effect(
        effect_type="акне", severity=2, on_date="2026-07-02"
    )
    assert row["effect_type"] == "акне"

    logs = await mcp_router.get_hrt_logs()
    assert [e["effect_type"] for e in logs["side_effects"]] == ["акне"]
    # It landed in HRT, not in GLP-1's side-effect table.
    assert (await mcp_router.get_glp1_logs())["side_effects"] == []

    assert "error" in await mcp_router.log_hrt_side_effect(effect_type="акне", severity=9)


async def test_close_and_delete_hrt_cycle():
    cycle = await mcp_router.add_hrt_cycle(kind="course", start_date="2026-06-01")
    item = await mcp_router.add_hrt_cycle_item(
        cycle["id"], compound_key="testosterone_enanthate", dose=250.0, interval_days=3.5
    )

    closed = await mcp_router.close_hrt_cycle(cycle["id"], end_date="2026-07-01")
    assert closed["end_date"] == "2026-07-01"
    # A closed cycle is no longer the active one.
    assert (await mcp_router.get_hrt_logs())["active_cycle"] is None

    # An end before the start would make the cycle vanish from history.
    assert "error" in await mcp_router.close_hrt_cycle(cycle["id"], end_date="2026-05-01")
    assert "error" in await mcp_router.close_hrt_cycle(9999)

    assert await mcp_router.delete_record("hrt_cycle_item", item["id"], confirm=True) == {
        "deleted": True,
        "domain": "hrt_cycle_item",
        "record_id": item["id"],
    }
    assert await mcp_router.delete_record("hrt_cycle", cycle["id"], confirm=True) == {
        "deleted": True,
        "domain": "hrt_cycle",
        "record_id": cycle["id"],
    }
    assert (await mcp_router.get_hrt_cycles())["cycles"] == []
