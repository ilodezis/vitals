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


def test_new_anthropometric_labels_bind_to_registry():
    # МедАсс sheet: height + waist/hip circumference + skeletal muscle mass %
    assert bm.normalize_metric("Рост")[0] == "height"
    assert bm.normalize_metric("Окружность талии")[0] == "waist_circumference"
    assert bm.normalize_metric("Окр. бедер")[0] == "hip_circumference"
    assert bm.normalize_metric("Доля скелетно-мышечной массы")[0] == "skeletal_muscle_mass_pct"
    assert bm.normalize_metric("Минеральная масса тела")[0] == "minerals"
    assert bm.normalize_metric("Соотношение талии/бедра")[0] == "waist_hip_ratio"
    assert bm.normalize_metric("Клеточная жидкость")[0] == "intracellular_water"
    # every new key is actually registered (would KeyError in normalize_metric otherwise)
    for key in ("height", "waist_circumference", "hip_circumference", "skeletal_muscle_mass_pct"):
        assert key in bm.METRIC_REGISTRY


def test_trailing_unit_annotation_is_stripped_before_matching():
    # МедАсс prints the unit inline in the label instead of a separate field.
    assert bm.normalize_metric("Тощая масса (кг)")[0] == "fat_free_mass"
    assert bm.normalize_metric("Процент жира (%)")[0] == "body_fat_pct"
    # unrecognised even after stripping still falls back to 'other' (no data lost)
    key, category, _ = bm.normalize_metric("Совершенно неизвестная штука (шт)")
    assert category == "other"


def test_multiple_trailing_unit_annotations_are_all_stripped():
    # a label can carry more than one trailing parenthetical (unit + abbreviation) —
    # each one is stripped in turn until a known label or a dead end is found.
    assert bm.normalize_metric("Индекс массы тела (BMI) (кг/м²)")[0] == "bmi"


def test_medass_device_specific_aliases_documented_by_pr2():
    """Locks in the two МедАсс aliases added in PR #2 (github.com/ilodezis/vitals/pull/2).

    Both are device-specific relabelings the PR author matched against a real
    МедАсс printout. FLAGGED FOR MANUAL RE-VERIFICATION against the original
    scan photo/PDF if body-fat % or body-fat-mass ever look wrong on a scan
    from this device — see PR #2 review notes:
      - "классификация по проценту жировой массы" is assumed to carry the
        numeric body-fat % reading itself, not a text/coded classification.
      - "жировая масса (кг), нормированная по росту" (height-normalized fat
        mass) is assumed to be device phrasing for plain fat mass, not a
        distinct Fat Mass Index (FMI = fat_kg / height_m²) value on a
        different scale.
    """
    assert bm.normalize_metric("Классификация по проценту жировой массы")[0] == "body_fat_pct"
    assert bm.normalize_metric("Жировая масса (кг), нормированная по росту")[0] == "body_fat_mass"


def test_new_inbody_russian_aliases():
    """Verify newly added Russian InBody translation aliases map correctly."""
    assert bm.normalize_metric("Масса скелетной мускулатуры")[0] == "skeletal_muscle_mass"
    assert bm.normalize_metric("Процентное содержание жира")[0] == "body_fat_pct"
    assert bm.normalize_metric("Содержание жира в теле")[0] == "body_fat_mass"
    assert bm.normalize_metric("Протеин")[0] == "protein"
    assert bm.normalize_metric("Полный фазовый угол тела")[0] == "phase_angle"
    assert bm.normalize_metric("Оценка InBody")[0] == "inbody_score"
    assert bm.normalize_metric("Общее количество воды в организме")[0] == "total_body_water"
    assert bm.normalize_metric("Внутриклеточная вода")[0] == "intracellular_water"
    assert bm.normalize_metric("Внеклеточная вода")[0] == "extracellular_water"
    assert bm.normalize_metric("Уровень базального метаболизма")[0] == "bmr"
    assert bm.normalize_metric("Индекс соотношения талия-бедра")[0] == "waist_hip_ratio"
    assert bm.normalize_metric("Активная масса клеток")[0] == "active_cell_mass"
    assert bm.normalize_metric("Соотношение ВКЖ/ОКЖ")[0] == "ecw_tbw_ratio"
    assert bm.normalize_metric("Идеальный вес")[0] == "target_weight"
