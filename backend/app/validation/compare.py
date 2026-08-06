"""Value normalisation and comparison primitives used by the engine."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

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


def parse_timestamp(value: Any) -> datetime | None:
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    try:
        parsed = pd.to_datetime(value, errors="coerce", format="mixed", dayfirst=False)
    except (ValueError, TypeError):
        return None
    if parsed is None or pd.isna(parsed):
        return None
    stamp = parsed.to_pydatetime() if isinstance(parsed, pd.Timestamp) else parsed
    return stamp.replace(tzinfo=None) if stamp.tzinfo else stamp
