"""Genetics reference service (Phase 3).

Static reference rows (added by hand or via ``scripts/import_vcf.py``). Their
``marker`` slugs are exposed to the conflict engine via :func:`resolve_variants`,
so a carrier variant can block a contraindicated supplement.
"""
from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import Source
from vitals.models.genetics import DOMAIN, GeneticVariant

# How many parsed VCF rows one import keeps in the data lake.
# ponytail: a consumer genome is ~600k rsID rows; storing all of them would put a
# ~20 MB JSON blob in one raw_payloads row (and hold it in RAM while parsing), so
# the import keeps the first 50k. If a re-parse ever needs the whole genome,
# store the gzipped file on disk and keep only its path here.
MAX_RAW_VARIANTS = 50_000


async def list_variants(session: AsyncSession) -> Sequence[GeneticVariant]:
    result = await session.execute(
        select(GeneticVariant).order_by(GeneticVariant.gene)
    )
    return result.scalars().all()


async def add_variant(
    session: AsyncSession,
    *,
    gene: str,
    rsid: Optional[str] = None,
    genotype: Optional[str] = None,
    marker: Optional[str] = None,
    impact: Optional[str] = None,
    impact_domain: Optional[str] = None,
    interpretation: Optional[str] = None,
    action_notes: Optional[str] = None,
    source: str = Source.MANUAL.value,
) -> GeneticVariant:
    row = GeneticVariant(
        domain=DOMAIN,
        source=source,
        gene=gene,
        rsid=rsid,
        genotype=genotype,
        marker=marker,
        impact=impact,
        impact_domain=impact_domain,
        interpretation=interpretation,
        action_notes=action_notes,
    )
    session.add(row)
    await session.flush()
    return row


async def upsert_by_rsid(
    session: AsyncSession,
    *,
    gene: str,
    rsid: str,
    genotype: Optional[str] = None,
    marker: Optional[str] = None,
    impact: Optional[str] = None,
    impact_domain: Optional[str] = None,
    interpretation: Optional[str] = None,
    action_notes: Optional[str] = None,
    source: str = Source.VCF_IMPORT.value,
) -> GeneticVariant:
    """Insert or update a variant keyed by rsid (used by the VCF importer so a
    re-import refreshes genotypes instead of duplicating)."""
    result = await session.execute(
        select(GeneticVariant).where(GeneticVariant.rsid == rsid)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return await add_variant(
            session,
            gene=gene,
            rsid=rsid,
            genotype=genotype,
            marker=marker,
            impact=impact,
            impact_domain=impact_domain,
            interpretation=interpretation,
            action_notes=action_notes,
            source=source,
        )
    row.gene = gene
    row.genotype = genotype
    if marker is not None:
        row.marker = marker
    if impact is not None:
        row.impact = impact
    if impact_domain is not None:
        row.impact_domain = impact_domain
    if interpretation is not None:
        row.interpretation = interpretation
    if action_notes is not None:
        row.action_notes = action_notes
    row.source = source
    await session.flush()
    return row


async def store_raw_vcf(
    session: AsyncSession,
    *,
    filename: Optional[str],
    variants: Sequence[Sequence[str]],
    truncated: bool = False,
) -> None:
    """Keep the parsed rows of an imported VCF in ``raw_payloads``.

    The importer writes only the rsIDs it can interpret today
    (``genetics_vcf.INTERPRETATIONS``); everything else used to be dropped on the
    floor, so expanding that table meant asking the owner to find and re-upload
    the file. Each variant is stored as ``[rsid, ref, alt, genotype]`` — the
    ParsedVariant fields, which is all ``interpret()`` needs to re-derive rows
    later — rather than the original VCF text.
    """
    from vitals.services import raw_payload_service

    await raw_payload_service.upsert_raw_payload(
        session,
        domain=DOMAIN,
        source=Source.VCF_IMPORT.value,
        external_id=(filename or "vcf")[:128],
        payload={"filename": filename, "truncated": truncated, "variants": list(variants)},
    )


async def delete_variant(session: AsyncSession, variant_id: int) -> bool:
    row = await session.get(GeneticVariant, variant_id)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def resolve_variants(session: AsyncSession) -> list[dict]:
    """Conflict-engine resolver: variants as match items (marker slugs)."""
    result = await session.execute(select(GeneticVariant))
    return [
        {"marker": v.marker, "gene": v.gene, "genotype": v.genotype}
        for v in result.scalars().all()
        if v.marker
    ]


# ── Full view collection for API / UI ─────────────────────────────────────────
async def collect(session: AsyncSession) -> dict[str, Any]:
    """Collect everything needed by the Genetics dashboard in one round-trip."""
    variants = await list_variants(session)
    items = []
    for v in variants:
        items.append({
            "id": v.id,
            "gene": v.gene,
            "rsid": v.rsid,
            "genotype": v.genotype,
            "gt": v.genotype,
            "marker": v.marker,
            "impact": v.impact,
            "impactDomain": v.impact_domain,
            "dom": v.impact_domain or "health",
            "interpretation": v.interpretation,
            "interp": v.interpretation,
            "actionNotes": v.action_notes,
            "action": v.action_notes,
            "source": v.source,
            "hasRisk": bool(v.marker),
        })
    return {
        "variants": items,
        "count": len(items),
        "empty": len(items) == 0,
    }

