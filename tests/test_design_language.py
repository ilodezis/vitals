"""Copy and number formats that must read one way across the app: the decimal
mark per language and the Russian UI strings that once had case errors."""

from vitals.i18n import STRINGS, current_lang


def test_one_decimal_mark_per_language():
    """A number input is drawn by the browser in the user's own locale — Chrome
    renders 86.1 as "86,1" under ru and no attribute changes that — so the
    readouts follow the platform instead of arguing with it. Three code paths
    printed a number to this dashboard and each rounded it its own way; they all
    go through `decimal()` now, so a weight cannot read two ways on one screen.
    """
    from vitals.services.nav_status_service import decimal as nav_decimal
    from vitals.services.today_service import _num, _signed
    from web.templating import format_number

    assert STRINGS["ru"]["common.decimal_sep"] == ","
    assert STRINGS["en"]["common.decimal_sep"] == "."
    assert nav_decimal is not None

    token = current_lang.set("ru")
    try:
        assert format_number(12345.67) == "12 345,7"
        assert _num(86.13) == "86,1"
        assert _signed(-0.63) == "−0,6"
    finally:
        current_lang.reset(token)
    assert format_number(12345.67) == "12 345.7"


def test_service_strings_and_case_errors_are_gone():
    ru = STRINGS["ru"]
    # "8h 40m" sat beside "Оценка сна".
    assert ru["common.hour_abbr"] == "ч"
    # "2 ПРОМАХОВ" — a caption takes the plain plural, not the form that only
    # agrees with five.
    assert ru["signals.metric_misparse"] == "Промахи"
    assert ru["glp1.toggle_form"] == "Новая запись"
    assert "{n}" in ru["charts.series_n"]
