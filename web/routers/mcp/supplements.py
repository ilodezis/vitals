"""Supplement catalog and genetic variants."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select

from vitals.enums import Source
from vitals.models import (
    GeneticVariant,
    Supplement,
)
from vitals.services.conflict_engine import ConflictBlocked
from web.routers.mcp._core import (
    READ, WRITE, _conflict_payload, _merged, gated, get_session_factory, route, serialize_row, serialize_written, tool,
)

@tool(READ, module='supplements')
async def get_supplements_catalog() -> list[dict]:
    """Retrieves the supplement catalog (taken and paused) with dosages and evidence
    tiers. ``periods`` is each one's start/stop history, oldest first: ``start``,
    ``end`` once stopped, ``inferred`` when the start was backfilled (may be later
    than the real one)."""
    from vitals.services import supplements_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(Supplement).order_by(Supplement.name)
        supps = (await session.execute(stmt)).scalars().all()
        history = await supplements_service.periods_by_supplement(session)
        out = []
        for s in supps:
            row = serialize_row(s)
            periods = supplements_service.periods_view(history.get(s.id, []))
            row["periods"] = periods or []
            out.append(row)
        return out


@tool(READ, module='genetics')
async def get_genetics_snps(
    gene: Optional[str] = None, rsid: Optional[str] = None, limit: int = 100
) -> list[dict]:
    """Retrieves digitized SNPs (genetic variants) with a description of their effect.
    Filter by ``gene`` ("MTHFR") or ``rsid`` ("rs1801133") — both match regardless of
    case. Unfiltered it returns the first ``limit`` variants in (gene, rsid) order;
    a whole-genome import is far larger than that, so ask for the marker you mean.
    READ tool."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(GeneticVariant)
        if gene:
            stmt = stmt.where(func.lower(GeneticVariant.gene) == gene.strip().lower())
        if rsid:
            stmt = stmt.where(func.lower(GeneticVariant.rsid) == rsid.strip().lower())
        stmt = stmt.order_by(GeneticVariant.gene, GeneticVariant.rsid).limit(limit)
        variants = (await session.execute(stmt)).scalars().all()
        return [serialize_row(v) for v in variants]


@tool(WRITE, module="genetics", idempotent=True)
@gated("genetics")
async def upsert_genetic_variant(
    gene: str,
    rsid: str,
    genotype: Optional[str] = None,
    marker: Optional[str] = None,
    impact: Optional[str] = None,
    impact_domain: Optional[str] = None,
    interpretation: Optional[str] = None,
    action_notes: Optional[str] = None,
) -> dict:
    """Adds or updates one genetic variant, keyed by ``rsid`` — restating a known
    rsid edits that row instead of duplicating it. ``marker`` is the slug the
    conflict rules match on (e.g. "mthfr_c677t_tt"); without one the variant is
    reference-only. Fields left out keep their stored value. WRITE tool."""
    from vitals.services import genetics_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        # upsert_by_rsid replaces the genotype unconditionally — the VCF importer
        # always has one. A conversation adding just an interpretation does not,
        # and must not blank the genotype the import wrote.
        if genotype is None:
            existing = (
                await session.execute(
                    select(GeneticVariant).where(GeneticVariant.rsid == rsid)
                )
            ).scalar_one_or_none()
            genotype = existing.genotype if existing is not None else None
        row = await genetics_service.upsert_by_rsid(
            session,
            gene=gene,
            rsid=rsid,
            genotype=genotype,
            marker=marker,
            impact=impact,
            impact_domain=impact_domain,
            interpretation=interpretation,
            action_notes=action_notes,
            source=Source.MCP.value,
        )
        await session.commit()
        return await serialize_written(session, row)


# ── Supplements catalog CRUD ──────────────────────────────────────────────────
@gated("supplements")
async def add_supplement(
    name: str,
    key: Optional[str] = None,
    dose: Optional[str] = None,
    timing: Optional[str] = None,
    evidence: Optional[str] = None,
    active: bool = True,
    contraindications: Optional[str] = None,
    note: Optional[str] = None,
    override: bool = False,
) -> dict:
    """Adds a supplement to the catalog (reference, not a daily log). ``key`` is the
    stable conflict-matching slug — omit it and it's derived from ``name`` (RU/EN
    aware). ``evidence`` is tier A/B/C. Activating a contraindicated supplement can
    hard-block → ``{"blocked": true, ...}``; retry with ``override=True``. WRITE tool."""
    from vitals.services import supplements_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            row = await supplements_service.add_supplement(
                session, name=name, key=key, dose=dose, timing=timing,
                evidence=evidence, active=active,
                contraindications=contraindications, note=note, override=override,
                source=Source.MCP.value,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        await session.commit()
        return await serialize_written(session, row)


@gated("supplements")
async def update_supplement(
    supplement_id: int,
    name: Optional[str] = None,
    key: Optional[str] = None,
    dose: Optional[str] = None,
    timing: Optional[str] = None,
    evidence: Optional[str] = None,
    active: Optional[bool] = None,
    contraindications: Optional[str] = None,
    note: Optional[str] = None,
    override: bool = False,
) -> dict:
    """Updates a catalog supplement by ID. Only the fields you pass are changed —
    a rename does not clear the dose or switch a paused supplement back on; use
    ``set_supplement_active`` (or pass ``active``) for that. Same conflict gate as
    add — a hard block returns ``{"blocked": true, ...}``; retry with
    ``override=True``. WRITE tool."""
    from vitals.services import supplements_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        merged = await _merged(
            session, Supplement, supplement_id,
            name=name, dose=dose, timing=timing, evidence=evidence,
            active=active, contraindications=contraindications, note=note,
        )
        if merged is None:
            return {"error": f"Supplement {supplement_id} not found"}
        try:
            # ``key`` stays as passed: left out, the service re-derives the
            # conflict-matching slug from the (possibly new) name, same as add.
            row = await supplements_service.update_supplement(
                session, supplement_id, key=key, override=override,
                source=Source.MCP.value, **merged,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        await session.commit()
        return await serialize_written(session, row)


@gated("supplements")
async def set_supplement_active(
    supplement_id: int, active: bool, override: bool = False
) -> dict:
    """Toggles a supplement's active flag. Activating a contraindicated one runs the
    conflict check → ``{"blocked": true, ...}`` unless ``override=True``.
    Deactivating resolves the conflict alerts that no longer apply. WRITE tool."""
    from vitals.services import supplements_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            row = await supplements_service.set_active(
                session, supplement_id, active, override=override,
                source=Source.MCP.value,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        if row is None:
            return {"error": f"Supplement {supplement_id} not found"}
        await session.commit()
        return await serialize_written(session, row)


# ── Consolidated write tool ──────────────────────────────────────────────────
@tool(WRITE, module="supplements")
@gated("supplements")
async def save_supplement(
    record_id: Optional[int] = None,
    name: Optional[str] = None,
    key: Optional[str] = None,
    dose: Optional[str] = None,
    timing: Optional[str] = None,
    evidence: Optional[str] = None,
    active: Optional[bool] = None,
    contraindications: Optional[str] = None,
    note: Optional[str] = None,
    override: Optional[bool] = None,
) -> dict:
    """Adds a supplement to the catalog (a reference, not a daily log) or edits one.

    Without ``record_id``: a new supplement — ``name`` required; ``key`` is the
    conflict-matching slug (omit it and it is derived from ``name``, RU/EN aware);
    ``evidence`` tier A/B/C; ``active`` defaults to true. With ``record_id`` (an
    ``id`` from ``get_supplements_catalog``): changes only the fields passed —
    ``active`` alone starts or pauses it (recorded in its period history;
    pausing resolves conflict alerts that no longer apply).

    Activating a contraindicated supplement can hard-block →
    ``{"blocked": true, ...}``; repeat with ``override=true`` only if the owner
    insists."""
    fields = dict(
        name=name, key=key, dose=dose, timing=timing, evidence=evidence,
        contraindications=contraindications, note=note,
    )
    if record_id is None:
        return await route(
            add_supplement, "save_supplement",
            {**fields, "active": active, "override": override},
        )
    if active is not None and all(v is None for v in fields.values()):
        return await route(
            set_supplement_active, "save_supplement",
            {"supplement_id": record_id, "active": active, "override": override},
        )
    return await route(
        update_supplement, "save_supplement",
        {**fields, "supplement_id": record_id, "active": active, "override": override},
    )
