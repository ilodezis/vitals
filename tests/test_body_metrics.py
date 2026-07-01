"""Pure unit tests for the body-composition metric registry (no DB)."""
from vitals.services.analytics import body_metrics as bm


def test_normalize_known_russian_labels():
    # МедАсс sheet (Russian)
    assert bm.normalize_metric("Процент жира") == ("body_fat_pct", "composition", None)
    assert bm.normalize_metric("Скелетно-мышечная масса") == ("skeletal_muscle_mass", "composition", None)
    assert bm.normalize_metric("Фазовый угол") == ("phase_angle", "score", None)
    assert bm.normalize_metric("Общая жидкость организма") == ("total_body_water", "water", None)


def test_normalize_known_english_labels():
    # InBody sheet (English / abbreviations)
    assert bm.normalize_metric("Skeletal Muscle Mass")[0] == "skeletal_muscle_mass"
    assert bm.normalize_metric("PBF")[0] == "body_fat_pct"
    assert bm.normalize_metric("Visceral Fat Area")[0] == "visceral_fat_area"
    assert bm.normalize_metric("TBW")[0] == "total_body_water"


def test_normalize_is_case_and_yo_insensitive():
    assert bm.normalize_metric("  ФАЗОВЫЙ  УГОЛ ")[0] == "phase_angle"
    # ё → е
    assert bm.normalize_metric("Отношение ВнеКЖ/ОВО")[0] == "ecw_tbw_ratio"


def test_unknown_label_is_captured_as_other_slug():
    key, category, segment = bm.normalize_metric("Какая-то неведомая метрика 2")
    assert category == "other"
    assert segment is None
    assert key and key != "other"  # a real slug, so nothing is lost


def test_segmental_rows_collapse_with_segment():
    assert bm.normalize_metric("Right Arm", "right_arm") == ("segmental_lean", "segmental", "right_arm")
    # a fat-context segmental label → segmental_fat, limb resolved from Russian
    assert bm.normalize_metric("Жир правая нога", "правая нога") == ("segmental_fat", "segmental", "right_leg")


def test_canonical_segment_aliases():
    assert bm.canonical_segment("Левая рука") == "left_arm"
    assert bm.canonical_segment("trunk") == "trunk"
    assert bm.canonical_segment("туловище") == "trunk"
    assert bm.canonical_segment("nonsense") is None
    assert bm.canonical_segment(None) is None


def test_headline_keys_stable_and_known():
    assert "body_fat_pct" in bm.HEADLINE_KEYS
    assert "skeletal_muscle_mass" in bm.HEADLINE_KEYS
    # every headline key is a real registry entry flagged headline
    for k in bm.HEADLINE_KEYS:
        assert bm.METRIC_REGISTRY[k].headline is True


def test_display_name_localised():
    assert bm.display_name("phase_angle", "ru") == "Фазовый угол"
    assert bm.display_name("phase_angle", "en") == "Phase Angle"
    assert bm.display_name("totally_unknown_key") is None


def test_body_fat_and_lbm_and_weight_extractors():
    metrics = [
        {"metric_key": "body_fat_pct", "value": 18.5},
        {"metric_key": "weight", "value": 80.0},
        {"metric_key": "lean_body_mass", "value": 65.2},
    ]
    assert bm.body_fat_pct_from_scan(metrics) == 18.5
    assert bm.lbm_from_scan(metrics) == 65.2  # explicit lean mass preferred
    assert bm.weight_from_scan(metrics) == 80.0


def test_lbm_derived_from_weight_and_fat_when_no_explicit():
    metrics = [
        {"metric_key": "body_fat_pct", "value": 20.0},
        {"metric_key": "weight", "value": 100.0},
    ]
    # 100 * (1 - 0.20) = 80.0
    assert bm.lbm_from_scan(metrics) == 80.0
    # explicit weight arg overrides the scan's own weight
    assert bm.lbm_from_scan(metrics, weight_kg=50.0) == 40.0


def test_extractors_return_none_when_absent():
    assert bm.body_fat_pct_from_scan([]) is None
    assert bm.lbm_from_scan([{"metric_key": "phase_angle", "value": 6}]) is None
    assert bm.weight_from_scan([]) is None


def test_extractors_accept_orm_like_objects():
    class _M:
        def __init__(self, k, v, seg=None):
            self.metric_key = k
            self.value = v
            self.segment = seg

    metrics = [_M("body_fat_pct", 15.0), _M("weight", 90.0)]
    assert bm.body_fat_pct_from_scan(metrics) == 15.0
    assert bm.lbm_from_scan(metrics) == 76.5  # 90*(1-0.15)
