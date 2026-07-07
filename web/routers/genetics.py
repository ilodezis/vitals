"""Endpoints for the genetics reference table."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

import io

from vitals.services.genetics_vcf import INTERPRETATIONS, interpret, parse_vcf_line
from vitals.enums import Domain, Source
from vitals.services import alerts_service, genetics_service
from web.deps import get_session, require_auth
from web.templating import templates
from web.uploads import VCF_EXTS, VCF_MAX_BYTES, read_capped, validate_extension

router = APIRouter(prefix="/genetics", tags=["genetics"])


def _redirect(request: Request) -> RedirectResponse:
    response = RedirectResponse(url="/genetics", status_code=status.HTTP_303_SEE_OTHER)
    if "hx-request" in request.headers:
        response.headers["HX-Redirect"] = "/genetics"
    return response


@router.get("", response_class=HTMLResponse)
async def genetics_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    variants = await genetics_service.list_variants(db)
    alerts = await alerts_service.list_active(db, domain=Domain.GENETICS.value)
    return templates.TemplateResponse(
        request,
        "genetics/index.html",
        {
            "username": username,
            "variants": variants,
            "alerts": alerts,
            # Transient import summary (?imported=&markers=), shown as a banner.
            "imported": request.query_params.get("imported"),
            "imported_markers": request.query_params.get("markers"),
        },
    )


@router.post("/import")
async def import_vcf(
    request: Request,
    file: UploadFile = File(...),
    only_interpreted: bool = Form(False),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    """Parse an uploaded ``.vcf`` and upsert the **curated** variants (those in
    ``INTERPRETATIONS``), keyed by rsID. A full consumer genome is ~600k lines;
    upserting every raw variant would hang the request (Cloudflare 524), and raw
    unknown rows aren't useful here — so we keep only the rsIDs we interpret
    (~dozens). ``only_interpreted`` narrows further to marker-bearing variants.

    Lines are membership-checked before any DB work, so even a large file does at
    most a few dozen upserts; the size cap bounds the in-memory read."""
    validate_extension(file.filename, VCF_EXTS)
    raw = await read_capped(file, max_bytes=VCF_MAX_BYTES)
    text = raw.decode("utf-8", errors="replace")

    imported = 0
    markers = 0
    for line in io.StringIO(text):
        # Cheap rsID gate before the (relatively costly) full parse + DB upsert.
        variant = parse_vcf_line(line)
        if variant is None or variant.rsid not in INTERPRETATIONS:
            continue
        fields = interpret(variant)
        if only_interpreted and not fields.get("marker"):
            continue
        await genetics_service.upsert_by_rsid(db, **fields)
        imported += 1
        if fields.get("marker"):
            markers += 1
    await db.commit()

    return RedirectResponse(
        url=f"/genetics?imported={imported}&markers={markers}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/save")
async def save_variant(
    request: Request,
    gene: str = Form(...),
    rsid: Optional[str] = Form(None),
    genotype: Optional[str] = Form(None),
    marker: Optional[str] = Form(None),
    impact: Optional[str] = Form(None),
    impact_domain: Optional[str] = Form(None),
    interpretation: Optional[str] = Form(None),
    action_notes: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    if rsid:
        # An rsID is a globally-unique dbSNP id (uq_genetic_variant_rsid): re-saving
        # the same one refreshes it in place instead of hitting the constraint —
        # same semantics as the VCF importer. A blank rsID falls through to a plain
        # insert (many manual, rsID-less rows may coexist).
        await genetics_service.upsert_by_rsid(
            db,
            gene=gene,
            rsid=rsid,
            genotype=genotype or None,
            marker=marker or None,
            impact=impact or None,
            impact_domain=impact_domain or None,
            interpretation=interpretation or None,
            action_notes=action_notes or None,
            source=Source.MANUAL.value,
        )
    else:
        await genetics_service.add_variant(
            db,
            gene=gene,
            rsid=None,
            genotype=genotype or None,
            marker=marker or None,
            impact=impact or None,
            impact_domain=impact_domain or None,
            interpretation=interpretation or None,
            action_notes=action_notes or None,
        )
    await db.commit()
    return _redirect(request)


@router.post("/{id}/delete")
async def delete_variant(
    request: Request,
    id: int,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    await genetics_service.delete_variant(db, id)
    await db.commit()
    return _redirect(request)
