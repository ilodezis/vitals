"""Domain enums — single source of truth for the status/domain/source strings
that the Insights Layer relies on (``InsightsMixin.domain``/``.source``,
``system_alerts.severity``, ``conflict_rules.rule_type``).

``StrEnum`` members *are* their string value, so they store directly in the
``VARCHAR`` columns and compare equal to plain strings — no migration coupling.
"""
from __future__ import annotations

from enum import StrEnum


class Severity(StrEnum):
    """system_alerts ladder (see services/alerts_service.py).

    - ``INFO``  — passive UI badge (noisy-weight period active, goal deadline near).
    - ``WARN``  — non-intrusive UI status only, never popups/modals (GLP-1 plateau,
      recovery low, Garmin MFA needed).
    - ``BLOCK`` — raised as a pre-save validation error; overridable via the
      conflict-engine flow.
    """

    INFO = "info"
    WARN = "warn"
    BLOCK = "block"


class RuleType(StrEnum):
    """conflict_rules kinds (data-driven cross-domain rules)."""

    HARD_BLOCK = "hard_block"          # block save unless overridden
    SOFT_WARN = "soft_warn"           # write an alert, never block
    TIMING_SEPARATION = "timing_separation"  # e.g. separate two items by N hours


class Domain(StrEnum):
    """Every log/metric row carries one of these in ``InsightsMixin.domain``.

    One per module (plus ``SYSTEM`` for infra/non-domain alerts), so mass export
    and analytical filtering are uniform across the data lake.
    """

    WEIGHT = "weight"
    GLP1 = "glp1"
    SUPPLEMENTS = "supplements"
    GENETICS = "genetics"
    SKINCARE = "skincare"
    WORKOUTS = "workouts"   # Hevy
    GARMIN = "garmin"       # activity & recovery
    LABS = "labs"
    NUTRITION = "nutrition"
    MILESTONES = "milestones"
    SYSTEM = "system"


class Evidence(StrEnum):
    """Strength-of-evidence tier for a supplement (catalog reference)."""

    A = "A"  # strong (meta-analyses / RCTs)
    B = "B"  # moderate
    C = "C"  # weak / anecdotal


class Drug(StrEnum):
    """GLP-1 receptor agonists tracked in the injection log / dose phases."""

    SEMAGLUTIDE = "semaglutide"
    TIRZEPATIDE = "tirzepatide"


class InjectionSite(StrEnum):
    """Subcutaneous injection sites for the body-map rotation grid. The user
    rotates sites to avoid lipohypertrophy; the grid surfaces the last-used one."""

    ABDOMEN_LEFT = "abdomen_left"
    ABDOMEN_RIGHT = "abdomen_right"
    THIGH_LEFT = "thigh_left"
    THIGH_RIGHT = "thigh_right"
    ARM_LEFT = "arm_left"
    ARM_RIGHT = "arm_right"


class LabFlag(StrEnum):
    """Out-of-range classification for a lab result (computed from value vs ref).

    ``CRITICAL_*`` is raised when the value is far outside the range (see
    ``labs_service.compute_flag``) and escalates the alert."""

    NORMAL = "normal"
    LOW = "low"
    HIGH = "high"
    CRITICAL_LOW = "critical_low"
    CRITICAL_HIGH = "critical_high"


class NoiseDirection(StrEnum):
    """Expected weight distortion direction during a noise period.

    - ``UP``      — noise pushed scale weight *up* vs real trend (creatine
                    loading, high-sodium day, menstrual water retention).
                    Real fat-loss trend is *better* than the raw numbers show.
    - ``DOWN``    — noise pushed scale weight *down* vs real trend (dehydration,
                    post-illness).  Real situation is *worse* than numbers show.
    - ``NEUTRAL`` — direction unknown / not relevant (use when unsure).
    """

    UP = "up"
    DOWN = "down"
    NEUTRAL = "neutral"


class MilestoneStatus(StrEnum):
    """Lifecycle of a goal card."""

    ACTIVE = "active"
    ACHIEVED = "achieved"
    MISSED = "missed"
    PAUSED = "paused"


class Source(StrEnum):
    """Provenance of a row — where the data came from."""

    MANUAL = "manual"
    GARMIN_API = "garmin_api"
    HEALTH_AUTO_EXPORT = "health_auto_export"  # Garmin backup channel (uploaded JSON)
    HEVY_API = "hevy_api"
    LAB_PARSER = "lab_parser"
    VCF_IMPORT = "vcf_import"
    SCHEDULER = "scheduler"
    SYSTEM = "system"
