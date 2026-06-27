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
