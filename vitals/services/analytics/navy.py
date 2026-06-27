"""US Navy body-fat method + lean body mass (metric / cm inputs).

Male (per the project spec):

    BF% = 495 / (1.0324 − 0.19077·log10(waist−neck) + 0.15456·log10(height)) − 450

Female (standard metric constants, gated behind ``sex='female'`` for the
open-source build — the single user is male):

    BF% = 495 / (1.29579 − 0.35004·log10(waist+hip−neck) + 0.22100·log10(height)) − 450

All measurements in centimetres. LBM:

    LBM = weight · (1 − BF%/100)
"""
from __future__ import annotations

import math
from typing import Optional


def navy_body_fat_pct(
    *,
    waist_cm: float,
    neck_cm: float,
    height_cm: float,
    sex: str = "male",
    hips_cm: Optional[float] = None,
) -> float:
    """Body-fat % via the Navy method. Raises ``ValueError`` on geometry that the
    log can't take (e.g. waist ≤ neck) or missing female inputs."""
    if height_cm <= 0:
        raise ValueError("height_cm must be positive")

    if sex == "female":
        if hips_cm is None:
            raise ValueError("hips_cm is required for the female formula")
        inner = waist_cm + hips_cm - neck_cm
        if inner <= 0:
            raise ValueError("waist + hips - neck must be positive")
        denom = (
            1.29579
            - 0.35004 * math.log10(inner)
            + 0.22100 * math.log10(height_cm)
        )
    else:
        inner = waist_cm - neck_cm
        if inner <= 0:
            raise ValueError("waist - neck must be positive")
        denom = (
            1.0324
            - 0.19077 * math.log10(inner)
            + 0.15456 * math.log10(height_cm)
        )

    if denom <= 0:
        raise ValueError("degenerate measurements (non-positive denominator)")

    bf = 495.0 / denom - 450.0
    return round(bf, 2)


def lean_body_mass_kg(weight_kg: float, body_fat_pct: float) -> float:
    """Lean body mass from weight + body-fat %."""
    return round(weight_kg * (1.0 - body_fat_pct / 100.0), 2)
