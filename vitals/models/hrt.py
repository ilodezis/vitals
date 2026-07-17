"""HRT / TRT domain models — hormone & anabolic-steroid cycle tracking.

Four tables, all ``domain = 'hrt'``:

  * ``hrt_compounds`` — the curated **molecule catalog** (reference, like
    ``supplements``/``conflict_rules``: no per-day ``InsightsMixin.date``). Seeded
    from ``vitals/data/hrt_compounds.yaml`` via ``hrt_catalog.sync_catalog``,
    keyed on a stable ``key`` slug. The user may add custom rows too.
  * ``hrt_compound_components`` — per-ester breakdown of a multi-ester blend
    (Sustanon/Omnadren) so the active-release curve can sum each ester's decay.
  * ``hrt_doses`` — the **actual administration log** (point metric,
    ``InsightsMixin``). Carries the grey-market provenance the user asked to
    track (brand / underground-lab / batch / measured concentration) as plain
    fields on the row — a molecule is sold under many brands, so brand never
    lives on the catalog.
  * ``hrt_side_effects`` — symptom log graded 1-5 (mirrors GLP-1).

Nothing here blocks: the domain is a harm-reduction tracker. Cross-domain
soft-warn rules (oral 17aa + high liver enzymes, high hematocrit + active
testosterone) live in the conflict-engine catalog, not in the schema.
"""
from __future__ import annotations

from datetime import date as date_type
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from vitals.enums import Domain
from vitals.models.base import Base, TimestampMixin
from vitals.models.mixins import InsightsMixin, insights_index

DOMAIN = Domain.HRT.value

_JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


class HrtCompound(Base, TimestampMixin):
    """A molecule in the reference catalog (testosterone ester, oral AAS, AI,
    SERM, GH/IGF/peptide, ...). Brand-agnostic — describes the substance, not a
    product. ``key`` is the stable slug the catalog upserts on and that a dose
    row snapshots."""

    __tablename__ = "hrt_compounds"
    __table_args__ = (
        Index("ix_hrt_compounds_key", "key", unique=True),
        Index("ix_hrt_compounds_active", "active"),
        Index("ix_hrt_compounds_class", "compound_class"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    domain: Mapped[str] = mapped_column(String(32), nullable=False, server_default=DOMAIN)
    source: Mapped[str] = mapped_column(String(32), nullable=False, server_default="manual")

    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    name_ru: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # Free string validated against the YAML catalog (not a DB enum) so the
    # catalog can grow new classes without a migration.
    compound_class: Mapped[str] = mapped_column(String(32), nullable=False)
    ester: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # vitals.enums.Route.
    route: Mapped[str] = mapped_column(String(32), nullable=False)
    # vitals.enums.DoseUnit — the unit a dose of this compound is logged in.
    dose_unit: Mapped[str] = mapped_column(String(8), nullable=False, server_default="mg")

    conc_mg_ml: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tablet_mg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    half_life_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Parent-hormone mass fraction of the esterified compound (e.g. 0.70 for
    # test enanthate) — converts administered mg into active-hormone mg for the
    # release graph. 1.0 for base hormones/orals.
    active_fraction: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("1.0"))
    # Tri-state: 'true' | 'false' | 'partial' (informational, for E2 management).
    aromatizes: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # Common street/short names — for search & log matching (NOT brands).
    aliases: Mapped[Optional[Any]] = mapped_column(_JSON_TYPE, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    components: Mapped[list["HrtCompoundComponent"]] = relationship(
        back_populates="compound",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class HrtCompoundComponent(Base, TimestampMixin):
    """One ester of a multi-ester blend, with its mg per ml. Empty for
    single-ester/oral compounds; populated for Sustanon-style blends so the
    active-release curve sums each ester's own half-life."""

    __tablename__ = "hrt_compound_components"
    __table_args__ = (
        Index("ix_hrt_compound_components_compound", "compound_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    compound_id: Mapped[int] = mapped_column(
        ForeignKey("hrt_compounds.id", ondelete="CASCADE"), nullable=False
    )
    ester: Mapped[str] = mapped_column(String(32), nullable=False)
    mg: Mapped[float] = mapped_column(Float, nullable=False)  # mg per ml

    compound: Mapped["HrtCompound"] = relationship(back_populates="components")


class HrtDose(Base, InsightsMixin, TimestampMixin):
    """A single administration (injection / tablet / application). ``dose`` is in
    ``unit`` (mg for AAS/esters, IU for GH, mcg for peptides). Injectables are
    entered as ``volume_ml`` × concentration; the service computes mg."""

    __tablename__ = "hrt_doses"
    __table_args__ = (
        insights_index(__tablename__),
        Index("ix_hrt_doses_compound_key", "compound_key"),
        CheckConstraint("dose > 0", name="ck_hrt_doses_dose_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # FK for joins; SET NULL so deleting a catalog entry never wipes history.
    compound_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("hrt_compounds.id", ondelete="SET NULL"), nullable=True
    )
    # Stable slug snapshot — the durable reference, survives catalog edits.
    compound_key: Mapped[str] = mapped_column(String(64), nullable=False)

    dose: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(8), nullable=False, server_default="mg")
    # Injectable draw + the concentration actually used (grey-market vials vary
    # from the catalog's typical value); null for orals.
    volume_ml: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    concentration_mg_ml: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Grey-market provenance the user asked to track — free text on the row.
    brand: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    lab: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    batch: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Body-map rotation site (vitals.enums.HrtInjectionSite); null for orals.
    site: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class HrtSideEffect(Base, InsightsMixin, TimestampMixin):
    """A reported side effect on a date, graded 1-5 (mirrors GLP-1)."""

    __tablename__ = "hrt_side_effects"
    __table_args__ = (
        insights_index(__tablename__),
        CheckConstraint(
            "severity >= 1 AND severity <= 5",
            name="ck_hrt_side_effects_severity_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    effect_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class HrtCycle(Base, TimestampMixin):
    """A protocol spanning a date range (``end_date`` null = ongoing), like the
    GLP-1 ``DosePhase`` — carries ``domain``/``source`` for uniform export but no
    single ``InsightsMixin.date``. Owns one plan item per compound; those items'
    schedules drive the planned-dose overlay and the injection reminder."""

    __tablename__ = "hrt_cycles"
    __table_args__ = (
        Index("ix_hrt_cycles_range", "domain", "start_date", "end_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    domain: Mapped[str] = mapped_column(String(32), nullable=False, server_default=DOMAIN)
    source: Mapped[str] = mapped_column(String(32), nullable=False, server_default="manual")

    name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # vitals.enums.CycleKind.
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    start_date: Mapped[date_type] = mapped_column(Date, nullable=False)
    end_date: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    items: Mapped[list["HrtCycleItem"]] = relationship(
        back_populates="cycle",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class HrtCycleItem(Base, TimestampMixin):
    """One compound's plan within a cycle. ``schedule`` is an ordered JSON list of
    segments — each ``{"dose", "interval_days", "duration_days"}`` (flat) or a
    linear ramp ``{"dose_start", "dose_end", "step", "step_every_days",
    "interval_days", "duration_days"}``. The schedule engine
    (``hrt_cycle_service.expand_item_schedule``) turns it into planned
    administrations off a fixed grid anchored at the cycle start."""

    __tablename__ = "hrt_cycle_items"
    __table_args__ = (
        Index("ix_hrt_cycle_items_cycle", "cycle_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(
        ForeignKey("hrt_cycles.id", ondelete="CASCADE"), nullable=False
    )
    compound_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("hrt_compounds.id", ondelete="SET NULL"), nullable=True
    )
    compound_key: Mapped[str] = mapped_column(String(64), nullable=False)
    unit: Mapped[str] = mapped_column(String(8), nullable=False, server_default="mg")
    schedule: Mapped[Any] = mapped_column(_JSON_TYPE, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    cycle: Mapped["HrtCycle"] = relationship(back_populates="items")
