"""``narrative_guard`` — the brief's LLM paragraph checked against its own numbers.

Pure text logic, no database. The first case is the real 2026-11-28 paragraph,
where HRV was above its baseline and the model still called it low.
"""
from vitals.services.proactive.narrative_guard import contradictions, is_clean

REAL_GARMIN = {
    "hrv_avg": 34,
    "body_battery_high": 85,
    "body_battery_low": 25,
    "sleep_score": 93,
    "resting_hr": 65,
    "baseline": {
        "hrv_avg": 31.1,
        "body_battery_high": 63.6,
        "sleep_score": 81.3,
        "resting_hr": 69.6,
    },
}

REAL_TEXT = (
    "Сегодня день после тренировки, но организм не успел восстановиться: HRV ниже нормы, "
    "а Body Battery упала до 25. Сегодня стоит сделать акцент на восстановление: легкая "
    "активность или полный отдых, и следить за питанием."
)


def test_real_case_flags_hrv_and_body_battery_only():
    items = contradictions(REAL_TEXT, REAL_GARMIN)
    assert len(items) == 2, items
    assert any(i.startswith("HRV") for i in items)
    assert any(i.startswith("body_battery_high") for i in items)
    joined = " ".join(items)
    assert "sleep" not in joined
    assert "resting" not in joined
    assert is_clean(REAL_TEXT, REAL_GARMIN) is False


def test_truthful_text_with_same_numbers_is_clean():
    text = "HRV выше нормы, сон отличный, пульс покоя ниже обычного"
    assert contradictions(text, REAL_GARMIN) == []
    assert is_clean(text, REAL_GARMIN) is True


def test_down_claim_is_fine_when_value_is_below_baseline():
    garmin = {"hrv_avg": 30, "baseline": {"hrv_avg": 31.1}}
    assert contradictions("HRV просел на этой неделе", garmin) == []
    assert contradictions("ВСР снизилась", garmin) == []


def test_down_claim_with_value_at_or_above_baseline_is_flagged():
    garmin = {"hrv_avg": 31.1, "baseline": {"hrv_avg": 31.1}}
    items = contradictions("HRV просел", garmin)
    assert len(items) == 1
    assert items[0].startswith("HRV")


def test_spo2_comparative_claim_without_baseline_is_flagged():
    garmin = {"spo2_lowest": 92, "baseline": {}}
    items = contradictions("SpO2 ниже нормы за ночь", garmin)
    assert len(items) == 1
    assert "spo2_lowest" in items[0]
    assert "no baseline" in items[0]


def test_missing_baseline_block_entirely_flags_comparative_claim():
    garmin = {"sleep_score": 70}
    assert len(contradictions("Сон хуже обычного", garmin)) == 1


def test_text_without_any_metric_is_clean():
    assert contradictions("Сегодня хороший день, отдыхай и пей воду.", REAL_GARMIN) == []
    assert contradictions("", REAL_GARMIN) == []


def test_mixed_clauses_judge_each_clause_on_its_own():
    garmin = {"hrv_avg": 30, "sleep_score": 93, "baseline": {"hrv_avg": 31.1, "sleep_score": 81.3}}
    assert contradictions("сон хороший, но HRV просел", garmin) == []


def test_up_claim_with_value_below_baseline_is_flagged():
    garmin = {"resting_hr": 65, "baseline": {"resting_hr": 69.6}}
    items = contradictions("Пульс покоя вырос", garmin)
    assert len(items) == 1
    assert items[0].startswith("resting HR")


def test_yo_and_ye_are_treated_the_same():
    garmin = {"resting_hr": 65, "baseline": {"resting_hr": 69.6}}
    assert contradictions("Пульс покоя снижён", garmin) == []
    garmin_high = {"resting_hr": 75, "baseline": {"resting_hr": 69.6}}
    assert len(contradictions("Пульс покоя снижен", garmin_high)) == 1


def test_negated_comparison_is_not_a_claim():
    garmin = {"hrv_avg": 34, "baseline": {"hrv_avg": 31.1}}
    assert contradictions("HRV не ниже нормы", garmin) == []


def test_body_battery_quoting_low_value_is_flagged_without_direction_word():
    text = "Body Battery 25 с утра"
    items = contradictions(text, REAL_GARMIN)
    assert len(items) == 1
    assert "body_battery_low" in items[0]


def test_body_battery_quoting_high_value_is_not_flagged():
    text = "Body Battery 85 с утра"
    assert contradictions(text, REAL_GARMIN) == []


def test_conjunction_splits_two_metrics_into_separate_clauses():
    # "и" splits the clause, so the HRV part carries no direction word and the
    # resting HR part (65 vs baseline 69.6) is a true "below" claim.
    text = "HRV и пульс покоя ниже нормы"
    assert contradictions(text, REAL_GARMIN) == []


def test_missing_value_is_not_flagged_when_baseline_exists():
    garmin = {"baseline": {"hrv_avg": 31.1}}
    assert contradictions("HRV выше нормы", garmin) == []
