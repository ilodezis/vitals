"""Unit tests for the Jinja ``format_number`` filter.

Regression: integers (Garmin steps/calories) used to crash on Python 3.11 because
``int`` has no ``.is_integer()`` (added in 3.12) — the Garmin dashboard 500'd."""
from __future__ import annotations

from web.templating import format_number, format_date
import datetime


def test_format_number_handles_int_without_is_integer():
    # The case that crashed: a plain int (steps).
    assert format_number(8000) == "8 000"
    assert format_number(1234567) == "1 234 567"


def test_format_number_floats():
    assert format_number(85.5) == "85.5"
    assert format_number(1000.0) == "1 000"  # whole float → no decimals


def test_format_number_passthrough_for_non_numbers():
    assert format_number(None) is None
    assert format_number("—") == "—"
    # bool is an int subclass but must not be reformatted to "1"/"0".
    assert format_number(True) is True


def test_format_date_handles_various_inputs():
    # Datetime and date objects
    assert format_date(datetime.date(2026, 6, 25)) == "25-06-2026"
    assert format_date(datetime.datetime(2026, 6, 25, 12, 30)) == "25-06-2026"
    
    # ISO strings
    assert format_date("2026-06-25") == "25-06-2026"
    assert format_date("2026-06-25 15:45:00") == "25-06-2026"
    
    # Already formatted or other styles
    assert format_date("25-06-2026") == "25-06-2026"
    assert format_date("25.06.2026") == "25-06-2026"
    
    # Non-date strings and None
    assert format_date(None) == ""
    assert format_date("") == ""
    assert format_date("invalid-date") == "invalid-date"
