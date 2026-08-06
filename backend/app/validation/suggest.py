"""Config auto-detection.

The delta file rarely uses the same column names as the data ("Issuer" for
"Id", "country" for "att1"), so the suggestions combine name similarity with
how well the actual values overlap.
"""

from __future__ import annotations

import re
from typing import Any

from ..models import ColumnMapping, TestConfig
from .compare import normalise, parse_timestamp

KEY_NAME_HINTS = ("id", "key", "code", "ref", "identifier", "isin", "issuer", "cusip", "sedol")
TIMESTAMP_NAME_HINTS = ("modif", "updat", "changed", "timestamp", "date", "time", "asof", "as_of")


def _tokens(name: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", name.casefold()) if t}


def _name_score(a: str, b: str) -> float:
    left, right = a.casefold().strip(), b.casefold().strip()
    if left == right:
        return 1.0
    ta, tb = _tokens(left), _tokens(right)
    if ta and ta == tb:
        return 0.9
    if ta & tb:
        return 0.6
    if left in right or right in left:
        return 0.5
    return 0.0


def _column_values(rows: list[dict[str, Any]], column: str) -> list[Any]:
    return [row.get(column) for row in rows]


def _value_set(rows: list[dict[str, Any]], column: str) -> set[Any]:
    return {v for v in (normalise(r.get(column)) for r in rows) if v is not None}


def _overlap(a: set[Any], b: set[Any]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a)


def _uniqueness(rows: list[dict[str, Any]], column: str) -> float:
    values = [normalise(v) for v in _column_values(rows, column)]
    present = [v for v in values if v is not None]
    if not present or len(present) < len(values):
        return 0.0
    return len(set(present)) / len(present)


def suggest_key_column(rows: list[dict[str, Any]], columns: list[str]) -> str | None:
    best, best_score = None, 0.0
    for index, column in enumerate(columns):
        unique = _uniqueness(rows, column)
        if unique < 1.0:
            continue
        score = unique
        if any(hint in column.casefold() for hint in KEY_NAME_HINTS):
            score += 0.5
        score += max(0.0, 0.2 - index * 0.05)  # left-most columns are likelier keys
        if score > best_score:
            best, best_score = column, score
    return best


def suggest_timestamp_column(rows: list[dict[str, Any]], columns: list[str]) -> str | None:
    best, best_score = None, 0.0
    sample = rows[:50]
    for column in columns:
        values = [v for v in _column_values(sample, column) if v is not None]
        if not values:
            continue
        parsed = sum(1 for v in values if parse_timestamp(v) is not None)
        ratio = parsed / len(values)
        if ratio < 0.8:
            continue
        score = ratio
        if any(hint in column.casefold() for hint in TIMESTAMP_NAME_HINTS):
            score += 1.0
        if score > best_score:
            best, best_score = column, score
    return best


def suggest_config(
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    delta: dict[str, Any] | None,
    current: TestConfig | None = None,
) -> TestConfig:
    """Fill in whatever the user has not chosen yet, leaving their picks alone."""

    config = (current or TestConfig()).model_copy(deep=True)
    data = before or after
    if data is None:
        return config

    data_columns: list[str] = data["columns"]
    data_rows: list[dict[str, Any]] = data["rows"]

    if not config.key_columns:
        key = suggest_key_column(data_rows, data_columns)
        config.key_columns = [key] if key else data_columns[:1]

    if config.last_modified_column is None:
        candidates = [c for c in data_columns if c not in config.key_columns]
        config.last_modified_column = suggest_timestamp_column(data_rows, candidates)

    if not config.compare_columns:
        after_columns = set(after["columns"]) if after else set(data_columns)
        config.compare_columns = [
            c
            for c in data_columns
            if c in after_columns
            and c not in config.key_columns
            and c != config.last_modified_column
        ]

    if delta is None:
        return config

    delta_columns: list[str] = delta["columns"]
    delta_rows: list[dict[str, Any]] = delta["rows"]

    if not config.delta_key_columns:
        config.delta_key_columns = _match_delta_keys(
            config.key_columns, data_rows, delta_columns, delta_rows
        )

    if not config.delta_column_map:
        config.delta_column_map = _match_delta_payload(
            config, data_rows, data_columns, delta_columns, delta_rows, after
        )

    return config


def _match_delta_keys(
    key_columns: list[str],
    data_rows: list[dict[str, Any]],
    delta_columns: list[str],
    delta_rows: list[dict[str, Any]],
) -> list[str]:
    matched: list[str] = []
    taken: set[str] = set()
    for key_column in key_columns:
        key_values = _value_set(data_rows, key_column)
        best, best_score = None, 0.0
        for candidate in delta_columns:
            if candidate in taken:
                continue
            score = _overlap(_value_set(delta_rows, candidate), key_values) + _name_score(
                candidate, key_column
            )
            if score > best_score:
                best, best_score = candidate, score
        chosen = best if best and best_score > 0.3 else key_column
        matched.append(chosen)
        taken.add(chosen)
    return matched


def _match_delta_payload(
    config: TestConfig,
    data_rows: list[dict[str, Any]],
    data_columns: list[str],
    delta_columns: list[str],
    delta_rows: list[dict[str, Any]],
    after: dict[str, Any] | None,
) -> list[ColumnMapping]:
    """Map each non-key delta column onto the data column it describes."""

    candidates = [
        c
        for c in data_columns
        if c not in config.key_columns and c != config.last_modified_column
    ]
    after_rows = after["rows"] if after else []
    mappings: list[ColumnMapping] = []
    taken: set[str] = set()

    for delta_column in delta_columns:
        if delta_column in config.delta_key_columns:
            continue
        delta_values = _value_set(delta_rows, delta_column)
        best, best_score = None, 0.0
        for target in candidates:
            if target in taken:
                continue
            observed = _value_set(data_rows, target) | _value_set(after_rows, target)
            score = _overlap(delta_values, observed) + _name_score(delta_column, target)
            if score > best_score:
                best, best_score = target, score
        if best and best_score >= 0.5:
            mappings.append(ColumnMapping(delta_column=delta_column, target_column=best))
            taken.add(best)
    return mappings
