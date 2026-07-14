"""Pure-logic tests for the intake card's macro-composition split (no DB)."""
from __future__ import annotations

import pytest

from vitals.services import nutrition_service


def test_macro_energy_shares_uses_atwater_factors():
    # 100g protein (400 kcal) + 100g fat (900 kcal) + 100g carbs (400 kcal) = 1700 kcal.
    # Fat weighs 9 kcal/g, so it dominates the split despite equal grams.
    shares = nutrition_service.macro_energy_shares(
        {"protein_g": 100, "fat_g": 100, "carbs_g": 100}
    )
    assert shares["protein"] == pytest.approx(23.5, abs=0.1)
    assert shares["fat"] == pytest.approx(52.9, abs=0.1)
    assert shares["carbs"] == pytest.approx(23.5, abs=0.1)
    assert round(sum(shares.values())) == 100


def test_macro_energy_shares_empty_day_is_all_zero():
    shares = nutrition_service.macro_energy_shares(
        {"protein_g": 0, "fat_g": 0, "carbs_g": 0}
    )
    assert shares == {"protein": 0.0, "fat": 0.0, "carbs": 0.0}


def test_macro_energy_shares_handles_missing_and_none_keys():
    # Totals dict may carry None (no macro logged) or omit keys entirely.
    shares = nutrition_service.macro_energy_shares({"protein_g": None, "carbs_g": 50})
    assert shares == {"protein": 0.0, "fat": 0.0, "carbs": 100.0}
