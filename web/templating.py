"""Jinja2 environment configuration and custom filters for the web interface."""
from __future__ import annotations

import os
from typing import Any

from fastapi.templating import Jinja2Templates

from vitals.i18n import t, get_js_strings, plural

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# Create templates object
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def format_number(value: Any) -> Any:
    """Format numeric values with space separators: e.g. 12345.67 -> "12 345.67"."""
    try:
        if isinstance(value, (int, float)):
            n = value
        else:
            n = float(value)
        # int has no .is_integer() before Python 3.12, and ``bool`` is an int
        # subclass we don't want to reformat — guard both before the float check.
        if isinstance(n, bool):
            return value
        if isinstance(n, int) or n.is_integer():
            return f"{int(n):,}".replace(",", " ")
        n = round(n, 1)
        if n.is_integer():
            return f"{int(n):,}".replace(",", " ")
        return f"{n:,.1f}".replace(",", " ")
    except (TypeError, ValueError):
        return value


def plural_ru(n: Any, one: str, few: str, many: str) -> str:
    """Pick the Russian plural form for ``n``: 1 → one, 2–4 → few, 0/5+ → many.
    e.g. ``{{ count | plural_ru('сессия', 'сессии', 'сессий') }}``."""
    try:
        n = abs(int(n))
    except (TypeError, ValueError):
        return many
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return few
    return many


def static_version(path: str) -> str:
    """Append a cache-busting timestamp param based on the file modification time."""
    try:
        if path.startswith("/static/"):
            rel_path = path[8:]
            file_path = os.path.join(STATIC_DIR, rel_path)
            if os.path.exists(file_path):
                return f"{path}?v={int(os.path.getmtime(file_path))}"
    except Exception:
        pass
    return path


def format_date(value: Any) -> str:
    """Format date values (string or datetime object) to DD-MM-YYYY format."""
    if not value:
        return ""
    import datetime
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.strftime("%d-%m-%Y")
    if isinstance(value, str):
        value_str = value.strip()
        import re
        if re.match(r"^\d{2}-\d{2}-\d{4}$", value_str):
            return value_str
        if re.match(r"^\d{2}\.\d{2}\.\d{4}$", value_str):
            return value_str.replace(".", "-")
        if re.match(r"^\d{4}-\d{2}-\d{2}$", value_str):
            parts = value_str.split("-")
            return f"{parts[2]}-{parts[1]}-{parts[0]}"
        if re.match(r"^\d{4}-\d{2}-\d{2}\s+.*$", value_str):
            date_part = value_str.split()[0]
            parts = date_part.split("-")
            return f"{parts[2]}-{parts[1]}-{parts[0]}"
    return str(value)


def meal_word(n: Any) -> str:
    """Russian plural for meal count: 1 приём, 2 приёма, 5 приёмов."""
    return plural_ru(n, "приём", "приёма", "приёмов")


# Register filters and globals
templates.env.filters["format_number"] = format_number
templates.env.filters["format_date"] = format_date
templates.env.filters["plural_ru"] = plural_ru
templates.env.filters["plural"] = lambda n, *args: plural(n, *args)
templates.env.filters["meal_word"] = meal_word
templates.env.globals["static_version"] = static_version
templates.env.globals["t"] = t
templates.env.globals["get_js_strings"] = get_js_strings
templates.env.globals["plural"] = plural
