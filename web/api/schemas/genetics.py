"""Pydantic schemas for the Genetics API (/api/v1/genetics)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class GeneticVariantItem(CamelModel):
    id: int
    gene: str
    rsid: Optional[str] = None
    genotype: Optional[str] = None
    gt: Optional[str] = None
    marker: Optional[str] = None
    impact: Optional[str] = None
    impact_domain: Optional[str] = None
    dom: Optional[str] = None
    interpretation: Optional[str] = None
    interp: Optional[str] = None
    action_notes: Optional[str] = None
    action: Optional[str] = None
    source: Optional[str] = None
    has_risk: bool = False


class GeneticsView(CamelModel):
    variants: list[GeneticVariantItem]
    count: int
    empty: bool = False


class GeneticVariantCreate(CamelModel):
    gene: str
    rsid: Optional[str] = None
    genotype: Optional[str] = None
    marker: Optional[str] = None
    impact: Optional[str] = None
    impact_domain: Optional[str] = None
    interpretation: Optional[str] = None
    action_notes: Optional[str] = None


class GeneticVariantCreated(BaseModel):
    id: int


class GeneticsUploadResponse(CamelModel):
    ok: bool = True
    imported: int
    markers: int
    truncated: bool = False
