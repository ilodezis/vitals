"""``/api/v1/genetics`` — Genetics variant catalog and VCF importer."""
from __future__ import annotations

from fastapi import Depends, File, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import Source
from vitals.services import genetics_service
from vitals.services.genetics_vcf import INTERPRETATIONS, interpret, parse_vcf_line
from web.api.errors import MUTATION_ERRORS, ApiRouter, not_found
from web.api.schemas.genetics import (
    GeneticVariantCreate,
    GeneticVariantCreated,
    GeneticsUploadResponse,
    GeneticsView,
)
from web.deps import get_session, require_auth
from web.uploads import VCF_EXTS, VCF_MAX_BYTES, iter_lines_capped, validate_extension

router = ApiRouter(prefix="/genetics", dependencies=[Depends(require_auth)])


@router.get("", response_model=GeneticsView)
async def read_genetics(db: AsyncSession = Depends(get_session)) -> GeneticsView:
    """The whole Genetics catalog in one request: interpreted variants,
    categories, and empty status."""
    data = await genetics_service.collect(db)
    return GeneticsView.model_validate(data)


@router.post(
    "/upload",
    response_model=GeneticsUploadResponse,
    responses=MUTATION_ERRORS,
)
async def upload_genetics_vcf(
    file: UploadFile = File(...),
    only_interpreted: bool = False,
    db: AsyncSession = Depends(get_session),
) -> GeneticsUploadResponse:
    """Upload and parse a genome `.vcf` file, upserting curated variants."""
    validate_extension(file.filename, VCF_EXTS)

    imported = 0
    markers = 0
    raw_variants: list[list[str]] = []
    truncated = False
    async for line in iter_lines_capped(file, max_bytes=VCF_MAX_BYTES):
        variant = parse_vcf_line(line)
        if variant is None:
            continue
        if len(raw_variants) < genetics_service.MAX_RAW_VARIANTS:
            raw_variants.append([variant.rsid, variant.ref, variant.alt, variant.genotype])
        else:
            truncated = True
        if variant.rsid not in INTERPRETATIONS:
            continue
        fields = interpret(variant)
        if only_interpreted and not fields.get("marker"):
            continue
        await genetics_service.upsert_by_rsid(db, **fields)
        imported += 1
        if fields.get("marker"):
            markers += 1

    if raw_variants:
        await genetics_service.store_raw_vcf(
            db, filename=file.filename, variants=raw_variants, truncated=truncated
        )
    await db.commit()

    return GeneticsUploadResponse(
        ok=True,
        imported=imported,
        markers=markers,
        truncated=truncated,
    )


@router.post(
    "/variants",
    status_code=status.HTTP_201_CREATED,
    response_model=GeneticVariantCreated,
    responses=MUTATION_ERRORS,
)
async def create_genetics_variant(
    body: GeneticVariantCreate, db: AsyncSession = Depends(get_session)
) -> GeneticVariantCreated:
    """Add a genetic variant manually or upsert if rsid is specified."""
    if not body.gene or not body.gene.strip():
        raise ValueError("gene is required")

    if body.rsid:
        row = await genetics_service.upsert_by_rsid(
            db,
            gene=body.gene.strip(),
            rsid=body.rsid.strip(),
            genotype=body.genotype,
            marker=body.marker,
            impact=body.impact,
            impact_domain=body.impact_domain,
            interpretation=body.interpretation,
            action_notes=body.action_notes,
            source=Source.MANUAL.value,
        )
    else:
        row = await genetics_service.add_variant(
            db,
            gene=body.gene.strip(),
            rsid=None,
            genotype=body.genotype,
            marker=body.marker,
            impact=body.impact,
            impact_domain=body.impact_domain,
            interpretation=body.interpretation,
            action_notes=body.action_notes,
            source=Source.MANUAL.value,
        )
    await db.commit()
    return GeneticVariantCreated(id=row.id)


@router.delete("/variants/{variant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_genetics_variant(
    variant_id: int, db: AsyncSession = Depends(get_session)
):
    """Delete a genetic variant."""
    if not await genetics_service.delete_variant(db, variant_id):
        return not_found()
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
