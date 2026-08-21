"""Value normalisation and comparison primitives used by the engine."""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Any

from dateutil import parser as _date_parser

BLANKS = {"", "null", "none", "nan", "n/a", "na", "-"}


def display(value: Any) -> str:
    """Human readable rendering used in the grid and in messages."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def normalise(value: Any, *, trim: bool = True, case_sensitive: bool = False) -> Any:
    """Reduce a raw cell to a comparable form.

    Numbers compare numerically (so ``1`` == ``1.0`` == ``"1"``) and everything
    else compares as text, optionally trimmed and case-folded.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value)
    if trim:
        text = text.strip()
    if text.lower() in BLANKS:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    return text if case_sensitive else text.casefold()


def values_equal(
    left: Any,
    right: Any,
    *,
    trim: bool = True,
    case_sensitive: bool = False,
    numeric_tolerance: float = 0.0,
) -> bool:
    # Identical raw values stay identical through trim/casefold, so this is a
    # safe shortcut — and the common case: most cells in a run are unchanged.
    if left == right:
        return True
    a = normalise(left, trim=trim, case_sensitive=case_sensitive)
    b = normalise(right, trim=trim, case_sensitive=case_sensitive)
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= numeric_tolerance
    return a == b


def key_of(row: dict[str, Any], columns: list[str], *, case_sensitive: bool = False) -> str:
    """Build the row identity used to join before/current/delta."""
    parts = []
    for column in columns:
        value = normalise(row.get(column), case_sensitive=case_sensitive)
        parts.append("" if value is None else display(value))
    return "||".join(parts)


@lru_cache(maxsize=8192)
def _parse_timestamp_text(text: str) -> datetime | None:
    # Timestamp columns are typically low-cardinality (a handful of batch
    # stamps repeated across many rows), so caching the parse of each
    # distinct string avoids re-parsing it on every row that shares it.
    try:
        parsed = _date_parser.parse(text, dayfirst=False)
    except (ValueError, OverflowError, TypeError):
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    text = str(value).strip()
    if not text:
        return None
    return _parse_timestamp_text(text)
