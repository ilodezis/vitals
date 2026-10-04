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

    - ``NOTE``  — an *interpretation*, never a failure: the app read the data and
      has something to say about it (recovery is low, the dose has plateaued).
      Nothing is broken, nothing needs dismissing, and it never blocks a save.
      Split out of ``WARN`` because painting a reading of the numbers in the same
      amber as "Garmin needs MFA" taught the owner to ignore both.
    - ``INFO``  — passive UI badge (noisy-weight period active, goal deadline near).
    - ``WARN``  — non-intrusive UI status only, never popups/modals (Garmin MFA
      needed, an integration stopped syncing).
    - ``BLOCK`` — raised as a pre-save validation error; overridable via the
      conflict-engine flow.

    The column is a plain ``VARCHAR(16)`` with no CHECK constraint, so adding a
    member needs no migration.
    """

    NOTE = "note"
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
    BODY_COMPOSITION = "body_comp"  # InBody / МедАсс BIA scans (lives under /weight)
    GLP1 = "glp1"
    SUPPLEMENTS = "supplements"
    GENETICS = "genetics"
    SKINCARE = "skincare"
    WORKOUTS = "workouts"   # Hevy
    GARMIN = "garmin"       # activity & recovery
    LABS = "labs"
    NUTRITION = "nutrition"
    HRT = "hrt"  # hormone/TRT/AAS cycles, estrogen control, GH/IGF-1/peptides
    MILESTONES = "milestones"
    TIMELINE = "timeline"  # global annotations shown across every domain's chart
    SIGNALS = "signals"  # free-text capture: how the day actually felt (+ day context)
    ENVIRONMENT = "environment"  # the bedroom's air: CO2, temperature, humidity (a sensor station)
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


class Route(StrEnum):
    """Administration route for an HRT compound / dose (vitals.models.hrt)."""

    INTRAMUSCULAR = "intramuscular"
    SUBCUTANEOUS = "subcutaneous"
    ORAL = "oral"
    TRANSDERMAL = "transdermal"


class DoseUnit(StrEnum):
    """Unit a dose is measured in. Injectable AAS/esters are mg; growth hormone
    and gonadotropins are IU; most peptides and IGF-1 analogs are mcg."""

    MG = "mg"
    IU = "iu"
    MCG = "mcg"


class HrtInjectionSite(StrEnum):
    """Intramuscular/subcutaneous sites for the HRT body-map rotation grid — the
    deeper IM depots used for oil-based esters, distinct from the GLP-1 subcut
    grid (``InjectionSite``). The user rotates sites to avoid scar tissue/PIP."""

    GLUTE_LEFT = "glute_left"
    GLUTE_RIGHT = "glute_right"
    VENTROGLUTE_LEFT = "ventroglute_left"
    VENTROGLUTE_RIGHT = "ventroglute_right"
    DELT_LEFT = "delt_left"
    DELT_RIGHT = "delt_right"
    QUAD_LEFT = "quad_left"
    QUAD_RIGHT = "quad_right"
    VGL_LEFT = "vastus_lateralis_left"
    VGL_RIGHT = "vastus_lateralis_right"


class CycleKind(StrEnum):
    """Kind of an HRT cycle (vitals.models.hrt.HrtCycle) — shapes the lab-check
    cadence. Deliberately just two: the app only *behaves* differently for
    "on hormones" vs "restarting natural production", so pretending to five
    kinds (TRT/blast/cruise/bridge...) was labeling, not function — use the
    cycle's free-text name for that nuance. (Collapsed in migration 0028.)"""

    COURSE = "course"  # any exogenous-hormone protocol (TRT, blast, cruise...)
    PCT = "pct"        # post-cycle therapy (SERM/HCG restart)


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


class AnnotationKind(StrEnum):
    """Timeline annotation categories — flags the owner drops on the calendar
    (trip, illness, protocol change) that have no natural home in any single
    domain table."""

    LIFE_EVENT = "life_event"
    ILLNESS = "illness"
    TRAVEL = "travel"
    PROTOCOL_CHANGE = "protocol_change"
    NOTE = "note"


class MilestoneStatus(StrEnum):
    """Lifecycle of a goal card."""

    ACTIVE = "active"
    ACHIEVED = "achieved"
    MISSED = "missed"
    PAUSED = "paused"


class SignalKind(StrEnum):
    """Shape of a ``signals`` row — what the entry lets you *do* downstream.

    - ``STATE``    — always present, has an intensity ("энергии ноль") → a line
      plotted next to HRV/sleep.
    - ``SYMPTOM``  — happened, has a severity ("голова раскалывается") →
      frequency + severity over time.
    - ``EXPOSURE`` — something taken/done ("кофе в 22") → yesterday's exposure
      vs. today's Garmin metric.

    Day *events* (illness, travel, protocol change) do **not** live here — they
    are ``timeline`` annotations and the digest already reads them.
    """

    STATE = "state"
    SYMPTOM = "symptom"
    EXPOSURE = "exposure"


class DigestKind(StrEnum):
    """Which narrative a ``weekly_digests`` row holds.

    All three are the same artifact — text plus the context it was built from — so
    they share one table and one page instead of growing a second store per
    cadence. ``WEEKLY`` is the historical default, which is why existing rows
    backfill to it.
    """

    WEEKLY = "weekly"
    DAILY_BRIEF = "daily_brief"
    EVENING = "evening"


class Source(StrEnum):
    """Provenance of a row — where the data came from."""

    MANUAL = "manual"
    # Written through the MCP connector (a conversation with Claude). Still the
    # owner talking, so it ranks with MANUAL wherever provenance decides who wins
    # — it only says which surface he used.
    MCP = "mcp"
    GARMIN_API = "garmin_api"
    HEALTH_AUTO_EXPORT = "health_auto_export"  # Garmin backup channel (uploaded JSON)
    HEVY_API = "hevy_api"
    LAB_PARSER = "lab_parser"
    BODY_SCAN = "body_scan"  # InBody / МедАсс body-composition scan (vision-parsed or manual)
    VCF_IMPORT = "vcf_import"
    TELEGRAM = "telegram"  # free-text captured by the bot, parsed into `signals`
    ESPHOME = "esphome"  # the home sensor station (polled over the LAN)
    # The week template *guessed* this day's context (vs. MANUAL — the owner
    # actually answered). Deliberately reusing MANUAL for "user" rather than
    # adding a second word for the same provenance.
    TEMPLATE = "template"
    SCHEDULER = "scheduler"
    SYSTEM = "system"
