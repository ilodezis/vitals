"""Per-limb rows of a body-composition sheet are filed by what they measure,
repeats are merged, and the snapshot leaves segments out. Synthetic values."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from vitals.enums import Domain, Source
from vitals.models.body_scan import BodyScan, BodyScanMetric
from vitals.services import body_scan_service, digest_service, modules_service

DAY = date(2026, 3, 10)

# What a vision model reads off an InBody-style sheet: the weight twice, the
# lean and fat tables, ECW/TBW and impedance per limb.
_EXTRACTED = {
    "date": "2026-03-01",
    "metrics": [
        {"label": "Weight", "value": 90.0, "unit": None, "ref_low": 60, "ref_high": 80},
        {"label": "Weight", "value": 90.0, "unit": "kg"},
        {"label": "Segmental Lean Analysis", "value": 3.9, "unit": "kg", "segment": "right_arm"},
        {"label": "Segmental Lean Analysis", "value": 101.0, "unit": "%", "segment": "right_arm"},
        {"label": "Segmental Fat Analysis", "value": 2.0, "unit": "kg", "segment": "right_arm"},
        {"label": "Segmental Fat Analysis", "value": 250.0, "unit": "%", "segment": "right_arm"},
        {"label": "ECW/TBW", "value": 0.37, "unit": None, "segment": "right_arm"},
        {"label": "Z(Ω) 50 kHz", "value": 290.0, "unit": None, "segment": "right_arm"},
    ],
}


def test_extraction_files_each_limb_row_under_its_own_key():
    rows = body_scan_service.normalize_extracted(_EXTRACTED)
    by_key = {(r["metric_key"], r["segment"]): r for r in rows}

    assert len(rows) == 7, "the repeated weight is one row"
    weight = by_key[("weight", None)]
    assert (weight["unit"], weight["ref_low"], weight["ref_high"]) == ("kg", 60, 80)
    assert by_key[("segmental_lean", "right_arm")]["value"] == 3.9
    assert by_key[("segmental_lean_pct", "right_arm")]["value"] == 101.0
    assert by_key[("segmental_fat", "right_arm")]["value"] == 2.0
    assert by_key[("segmental_fat_pct", "right_arm")]["value"] == 250.0
    assert by_key[("segmental_ecw_ratio", "right_arm")]["value"] == 0.37
    assert by_key[("segmental_impedance_50khz", "right_arm")]["value"] == 290.0

    units: dict[str, set] = {}
    for r in rows:
        units.setdefault(r["metric_key"], set()).add(r["unit"])
    assert all(len(u) == 1 for u in units.values()), units


def test_rows_that_disagree_are_both_kept():
    rows = body_scan_service.dedupe_rows([
        {"metric_key": "weight", "segment": None, "value": 90.0, "unit": "kg", "ref_low": None, "ref_high": None},
        {"metric_key": "weight", "segment": None, "value": 91.0, "unit": "kg", "ref_low": None, "ref_high": None},
    ])
    assert [r["value"] for r in rows] == [90.0, 91.0]


async def test_save_scan_stores_a_repeat_once(db_session):
    scan = await body_scan_service.save_scan(
        db_session, on_date=DAY, device="Synthetic",
        metrics=body_scan_service.normalize_extracted(_EXTRACTED) + [
            {"label": "Weight", "value": 90.0, "unit": "kg"},
        ],
    )
    await db_session.commit()
    stored = (await db_session.execute(
        select(BodyScanMetric).where(BodyScanMetric.scan_id == scan.id)
    )).scalars().all()
    assert sum(1 for m in stored if m.metric_key == "weight") == 1


def _scan(on: date, metrics: list[tuple]) -> BodyScan:
    scan = BodyScan(
        date=on, domain=Domain.BODY_COMPOSITION.value, source=Source.BODY_SCAN.value,
        device="Synthetic",
    )
    scan.metrics.extend(
        BodyScanMetric(metric_key=k, label=k, value=v, unit=u, segment=s, category=c)
        for k, v, u, s, c in metrics
    )
    return scan


async def test_snapshot_leaves_segments_out_and_merges_repeats(db_session):
    legacy = [
        ("weight", 95.0, None, None, "composition"),
        ("weight", 95.0, "kg", None, "composition"),
        ("body_fat_pct", 30.0, "%", None, "composition"),
        # Old parser output: impedance and a % filed as lean.
        ("segmental_lean", 340.0, None, "right_arm", "segmental"),
        ("segmental_lean", 4.0, "kg", "right_arm", "segmental"),
    ]
    db_session.add(_scan(DAY - timedelta(days=30), legacy))
    db_session.add(_scan(DAY - timedelta(days=2), [
        ("weight", 93.0, "kg", None, "composition"),
        ("body_fat_pct", 29.0, "%", None, "composition"),
        ("segmental_lean", 100.0, "%", "right_arm", "segmental"),
        ("segmental_fat_pct", 250.0, "%", "right_arm", "segmental"),
    ]))
    await modules_service.set_module_enabled(db_session, key="body_comp", enabled=True)
    await db_session.commit()

    ctx = await digest_service.assemble_context(db_session, on_date=DAY, period_days=7)
    body = ctx["body_comp"]
    for scan in body["scans"]:
        assert all(m["segment"] is None for m in scan["metrics"]), scan["metrics"]
        keys = [m["key"] for m in scan["metrics"]]
        assert len(keys) == len(set(keys)), keys
    assert all(d["segment"] is None for d in body["deltas_from_previous_scan"])
    deltas = {d["key"]: d["value"] for d in body["deltas_from_previous_scan"]}
    assert (deltas["weight"], deltas["body_fat_pct"]) == (-2.0, -1.0)
