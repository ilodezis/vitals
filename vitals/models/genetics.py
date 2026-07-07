"""Phase 3 — Genetics reference table.

Static reference (no per-day date): one row per interpreted variant. Populated
manually or via ``scripts/import_vcf.py`` (Genotek VCF). Like supplements it keeps
``domain``/``source`` for export but no ``InsightsMixin.date``.

``marker`` is a stable slug the **conflict engine** matches on
(``{"marker": "hemochromatosis_carrier"}``) — derived from the genotype, set by
the importer or by hand — so a rule fires regardless of how the gene/rsid is
spelled. ``impact_domain`` records which health domain the variant informs.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from vitals.enums import Domain
from vitals.models.base import Base, TimestampMixin

DOMAIN = Domain.GENETICS.value


class GeneticVariant(Base, TimestampMixin):
    __tablename__ = "genetic_variants"
    __table_args__ = (
        Index("ix_genetic_variants_marker", "marker"),
        # An rsID is a globally-unique dbSNP identifier — at most one row per rsid,
        # so a re-import or manual re-add refreshes in place instead of silently
        # duplicating (enforced; upsert_by_rsid relies on it). Partial so manual
        # rows with no rsid (NULL) can still coexist freely. Also serves rsid
        # lookups for the non-null values (the only ones ever queried by rsid).
        Index(
            "uq_genetic_variant_rsid",
            "rsid",
            unique=True,
            postgresql_where=text("rsid IS NOT NULL"),
            sqlite_where=text("rsid IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    domain: Mapped[str] = mapped_column(String(32), nullable=False, server_default=DOMAIN)
    source: Mapped[str] = mapped_column(String(32), nullable=False, server_default="manual")

    gene: Mapped[str] = mapped_column(String(64), nullable=False)
    rsid: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    genotype: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # Stable slug for conflict-rule matching (e.g. 'hemochromatosis_carrier').
    marker: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    impact: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # Which health domain this variant informs (supplements, skincare, ...).
    impact_domain: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    interpretation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    action_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
