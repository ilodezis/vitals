"""``/api/v1/weight`` — bodies and views for weight, measurements, noise markers, photos, and scans."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from pydantic import BaseModel


class WeightLogCreate(BaseModel):
    date: dt.date
    # Range-checked by the service, so a bad number is a 400 with its message and
    # the MCP tools and the old form are held to the same bounds.
    weight_kg: float
    note: Optional[str] = None
    # Repeat a write the conflict engine blocked (409) and keep it anyway.
    override: bool = False


class WeightLogPatch(BaseModel):
    """What to change; what is left out stays. ``note`` is the one field where an
    explicit ``null`` means something: it clears the note."""

    date: Optional[dt.date] = None
    weight_kg: Optional[float] = None
    note: Optional[str] = None
    override: bool = False


class WeightLogRef(BaseModel):
    """The row a write ended up on. Moving a reading to another day makes a new row,
    so a patch answers with the id to use from then on."""

    id: int


class WeightLogCreated(WeightLogRef):
    # False when the same reading was already there: the row that comes back is the
    # old one, and "Undo" for it would delete something the owner did not just make.
    created: bool


# ── Weight View (GET /api/v1/weight) ──────────────────────────────────────────


class WeightPoint(BaseModel):
    date: dt.date
    kg: float


class DosePhase(BaseModel):
    from_date: dt.date
    to_date: Optional[dt.date] = None
    drug: str
    dose_mg: float


class WeightHistoryItem(BaseModel):
    id: int
    date: dt.date
    time: str = ""
    weight_kg: float
    source: str
    superseded: bool = False
    superseded_by: Optional[str] = None
    note: Optional[str] = None


class WeightPaceDose(BaseModel):
    drug: Optional[str] = None
    dose_mg: Optional[float] = None
    since_date: dt.date
    days: int
    # ``None`` until the phase holds two weigh-ins to take a difference of.
    delta_kg: Optional[float] = None


class WeightPaceGoal(BaseModel):
    target_kg: float
    weeks: Optional[int] = None


class WeightPace(BaseModel):
    per_week_kg: Optional[float] = None
    dose: Optional[WeightPaceDose] = None
    goal: Optional[WeightPaceGoal] = None


class LastScanRow(BaseModel):
    label: str
    value: float
    unit: Optional[str] = None


class LastScanSummary(BaseModel):
    device: Optional[str] = None
    date: dt.date
    rows: list[LastScanRow] = []


class WeightView(BaseModel):
    latest_kg: Optional[float] = None
    latest_date: Optional[dt.date] = None
    average7: Optional[float] = None
    week_delta_kg: Optional[float] = None
    body_fat_pct: Optional[float] = None
    body_fat_source: Optional[str] = None
    drug: str = "GLP-1"
    weighings: list[WeightPoint] = []
    trend: list[WeightPoint] = []
    dose_phases: list[DosePhase] = []
    history: list[WeightHistoryItem] = []
    pace: WeightPace
    last_scan: Optional[LastScanSummary] = None


# ── Measures View & Mutations (GET /api/v1/weight/measures) ───────────────────


class BodyMeasurementCreate(BaseModel):
    date: dt.date
    neck_cm: Optional[float] = None
    waist_cm: Optional[float] = None
    hips_cm: Optional[float] = None
    note: Optional[str] = None
    override: bool = False


class BodyMeasurementPatch(BodyMeasurementCreate):
    """The whole row as the edit form holds it: a field left out is cleared, not kept."""


class BodyMeasurementRef(BaseModel):
    id: int
    body_fat_pct: Optional[float] = None
    lbm_kg: Optional[float] = None


class BodyMeasurementItem(BaseModel):
    id: int
    date: dt.date
    neck_cm: Optional[float] = None
    waist_cm: Optional[float] = None
    hips_cm: Optional[float] = None
    body_fat_pct: Optional[float] = None
    lbm_kg: Optional[float] = None
    source: str
    source_label: str
    note: Optional[str] = None


class NoiseMarkerCreate(BaseModel):
    start_date: dt.date
    end_date: Optional[dt.date] = None
    reason: str
    direction: Optional[str] = None


class NoiseMarkerRef(BaseModel):
    id: int


class NoiseMarkerItem(BaseModel):
    id: int
    start_date: dt.date
    end_date: Optional[dt.date] = None
    reason: str
    direction: Optional[str] = None


class ProgressPhotoItem(BaseModel):
    id: int
    date: dt.date
    file_key: str
    url: str
    note: Optional[str] = None


class BodyScanMetricItem(BaseModel):
    id: Optional[int] = None
    metric_key: Optional[str] = None
    label: str
    value: float
    unit: Optional[str] = None
    ref_low: Optional[float] = None
    ref_high: Optional[float] = None
    segment: Optional[str] = None
    category: Optional[str] = None


BodyScanMetricIn = BodyScanMetricItem


class BodyScanDetailItem(BaseModel):
    id: int
    date: dt.date
    device: Optional[str] = None
    file_key: Optional[str] = None
    note: Optional[str] = None
    metrics_count: int
    metrics: list[BodyScanMetricItem] = []


class BodyScanPreview(BaseModel):
    date: dt.date
    device: Optional[str] = None
    file_key: str
    raw_payload_id: int
    metrics: list[BodyScanMetricItem] = []


class BodyScanUploadResponse(BaseModel):
    ok: bool
    reason: Optional[str] = None
    message: Optional[str] = None
    scan: Optional[BodyScanPreview] = None


class BodyScanConfirm(BaseModel):
    date: dt.date
    device: Optional[str] = None
    file_key: Optional[str] = None
    raw_payload_id: Optional[int] = None
    note: Optional[str] = None
    override: bool = False
    metrics: list[BodyScanMetricItem] = []


class BodyScanConfirmResponse(BaseModel):
    ok: bool
    scan_id: Optional[int] = None


class WeightMeasuresView(BaseModel):
    latest_kg: Optional[float] = None
    average7: Optional[float] = None
    body_fat_pct: Optional[float] = None
    body_fat_source: Optional[str] = None
    week_delta_kg: Optional[float] = None
    height_cm: float
    sex: str
    body_comp_enabled: bool = False
    llm_configured: bool = False
    headline_metrics: list[LastScanRow] = []
    measurements: list[BodyMeasurementItem] = []
    scans: list[BodyScanDetailItem] = []
    photos: list[ProgressPhotoItem] = []
    noise_markers: list[NoiseMarkerItem] = []


class GarminExportResponse(BaseModel):
    ok: bool
    status: str
    last_error: Optional[str] = None
    next_attempt_at: Optional[dt.datetime] = None
