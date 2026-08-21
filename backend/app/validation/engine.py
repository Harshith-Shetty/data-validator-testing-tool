"""Data capture validation engine.

The third file is not a diff — it is an **upsert feed**: a set of records that
were handed to the capture run to apply. A row appearing in it does not mean
the data had to change. Applying record ``{id: 7, country: uk}`` to a record
that already says ``uk`` is a legitimate no-op; applying it to a key that does
not exist yet is an insert.

So the engine does not ask "did this row change?". It builds the state the
current file *should* be in::

    expected = before, with every delta record applied as an upsert

and compares the actual current file against that. Update, no-op and insert
then fall out of one rule instead of needing three.

Cell verdicts
-------------
PASS  the cell holds the value it should
FAIL  the cell is wrong (update never landed, landed wrong, insert missing, or
      a value moved that the feed never asked to move)
WARN  suspicious but not provably wrong
INFO  not evaluated (key columns, or an inserted row's unmapped columns, whose
      correct value nothing in the three files can tell us)

A row's verdict is the worst among its cells; the run's is the worst among its
rows.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ..models import CellStatus, RowType, RuleCode, TestConfig, utcnow
from .compare import display, key_of, parse_timestamp, values_equal

logger = logging.getLogger(__name__)

_SEVERITY = {CellStatus.INFO: 0, CellStatus.PASS: 1, CellStatus.WARN: 2, CellStatus.FAIL: 3}

# How often to log progress through the row-by-row comparison, so a run over
# a large dataset shows it is moving instead of going quiet until it's done.
_PROGRESS_EVERY = 5000


def _worst(statuses: list[CellStatus]) -> CellStatus:
    return max(statuses, key=lambda s: _SEVERITY[s], default=CellStatus.INFO)


class ValidationError(ValueError):
    """Raised when the configuration cannot be applied to the datasets."""


def _index_rows(
    rows: list[dict[str, Any]], key_columns: list[str], *, case_sensitive: bool
) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """Index rows by key, reporting keys that appear more than once."""
    index: dict[str, dict[str, Any]] = {}
    duplicates: set[str] = set()
    for row in rows:
        key = key_of(row, key_columns, case_sensitive=case_sensitive)
        if key in index:
            duplicates.add(key)
            continue  # first occurrence wins
        index[key] = row
    return index, duplicates


def _resolve_compare_columns(
    config: TestConfig, before_columns: list[str], after_columns: list[str]
) -> list[str]:
    if config.compare_columns:
        selected = list(config.compare_columns)
    else:
        after_set = set(after_columns)
        selected = [c for c in before_columns if c in after_set]
    excluded = set(config.key_columns) | set(config.ignore_columns)
    if config.last_modified_column:
        excluded.add(config.last_modified_column)
    return [c for c in selected if c not in excluded]


def _cell(
    column: str,
    before: Any,
    after: Any,
    expected: Any,
    status: CellStatus,
    code: RuleCode,
    message: str = "",
    *,
    has_expected: bool = True,
) -> dict[str, Any]:
    return {
        "column": column,
        "before": display(before),
        "after": display(after),
        "expected": display(expected) if has_expected else None,
        "changed": display(before) != display(after),
        "status": status.value,
        "code": code.value,
        "message": message,
    }


def run_validation(
    before: dict[str, Any],
    after: dict[str, Any],
    delta: dict[str, Any],
    config: TestConfig,
) -> dict[str, Any]:
    started = time.time()
    started_at = utcnow()
    logger.info(
        "Validation starting: before=%d after=%d delta=%d rows",
        len(before["rows"]),
        len(after["rows"]),
        len(delta["rows"]),
    )

    if not config.key_columns:
        raise ValidationError("At least one key column is required.")
    delta_keys = config.delta_key_columns or config.key_columns
    if len(delta_keys) != len(config.key_columns):
        raise ValidationError("Delta key columns must line up one-to-one with the key columns.")

    cs = config.case_sensitive

    def eq(a: Any, b: Any) -> bool:
        return values_equal(
            a,
            b,
            trim=config.trim_whitespace,
            case_sensitive=cs,
            numeric_tolerance=config.numeric_tolerance,
        )

    before_index, before_dupes = _index_rows(before["rows"], config.key_columns, case_sensitive=cs)
    after_index, after_dupes = _index_rows(after["rows"], config.key_columns, case_sensitive=cs)
    delta_index, delta_dupes = _index_rows(delta["rows"], delta_keys, case_sensitive=cs)

    compare_columns = _resolve_compare_columns(config, before["columns"], after["columns"])

    # data column -> the delta column that sets it
    setters: dict[str, str] = {
        target: source
        for source, target in config.mapping_dict().items()
        if source not in delta_keys and target
    }

    grid_columns = list(config.key_columns) + compare_columns
    if config.last_modified_column:
        grid_columns.append(config.last_modified_column)

    results: list[dict[str, Any]] = []
    issues: dict[str, int] = {}
    rows_by_type: dict[str, int] = {}

    def bump(counter: dict[str, int], code: str) -> None:
        counter[code] = counter.get(code, 0) + 1

    all_keys = list(dict.fromkeys(list(before_index) + list(after_index) + list(delta_index)))
    total_keys = len(all_keys)
    logger.info(
        "Indexed rows (%d ms); comparing %d unique keys...", int((time.time() - started) * 1000), total_keys
    )

    for processed, key in enumerate(all_keys, start=1):
        if processed % _PROGRESS_EVERY == 0:
            logger.info("Compared %d/%d rows...", processed, total_keys)
        before_row = before_index.get(key)
        after_row = after_index.get(key)
        delta_row = delta_index.get(key)

        cells: dict[str, dict[str, Any]] = {}
        messages: list[str] = []

        # --- what does the feed say should be true of this row? ------------------
        if before_row is not None:
            # Applying the delta record produces the expected state.
            expected_row = {c: before_row.get(c) for c in compare_columns}
            wants_change = False
            for column, source in setters.items():
                if delta_row is not None and column in compare_columns:
                    expected_row[column] = delta_row.get(source)
                    if not eq(before_row.get(column), delta_row.get(source)):
                        wants_change = True
            if delta_row is None:
                row_type = RowType.UNTOUCHED
            else:
                row_type = RowType.UPDATE_EXPECTED if wants_change else RowType.NOOP_EXPECTED
        else:
            expected_row = {
                column: (delta_row.get(source) if delta_row is not None else None)
                for column, source in setters.items()
                if column in compare_columns
            }
            wants_change = True
            row_type = RowType.INSERT_EXPECTED if delta_row is not None else RowType.UNEXPECTED_INSERT

        if after_row is None and before_row is not None:
            row_type = RowType.DELETED

        source_row = after_row or before_row or {}
        for index, column in enumerate(config.key_columns):
            value = source_row.get(column)
            if not value and delta_row is not None:
                value = delta_row.get(delta_keys[index])
            cells[column] = _cell(
                column, value, value, None, CellStatus.INFO, RuleCode.KEY, has_expected=False
            )

        # --- rows that never arrived ---------------------------------------------
        if after_row is None:
            if row_type is RowType.DELETED:
                code = RuleCode.ROW_MISSING_IN_AFTER
                note = "Row is in the before file but missing from the current file."
                status = CellStatus.FAIL if config.flag_deleted_rows else CellStatus.INFO
            else:
                code = RuleCode.MISSING_INSERT
                note = "The feed carries this record but it was never inserted."
                status = CellStatus.FAIL
            messages.append(note)
            bump(issues, code.value)
            for column in grid_columns:
                if column in config.key_columns:
                    continue
                cells[column] = _cell(
                    column,
                    (before_row or {}).get(column),
                    None,
                    expected_row.get(column),
                    status,
                    code,
                    note,
                    has_expected=column in expected_row,
                )
            bump(rows_by_type, row_type.value)
            results.append(_row(key, row_type, cells, messages))
            continue

        # --- a row nobody asked for ----------------------------------------------
        if row_type is RowType.UNEXPECTED_INSERT:
            note = "Row is in the current file but in neither the before file nor the feed."
            status = CellStatus.FAIL if config.flag_unexpected_inserts else CellStatus.INFO
            messages.append(note)
            bump(issues, RuleCode.UNEXPECTED_INSERT.value)
            for column in grid_columns:
                if column in config.key_columns:
                    continue
                cells[column] = _cell(
                    column,
                    None,
                    after_row.get(column),
                    None,
                    status,
                    RuleCode.UNEXPECTED_INSERT,
                    note,
                    has_expected=False,
                )
            bump(rows_by_type, row_type.value)
            results.append(_row(key, row_type, cells, messages))
            continue

        # --- compare against the expected state ----------------------------------
        for column in compare_columns:
            actual = after_row.get(column)

            if row_type is RowType.INSERT_EXPECTED:
                if column not in expected_row:
                    # Nothing in the three files says what this column should hold.
                    cells[column] = _cell(
                        column,
                        None,
                        actual,
                        None,
                        CellStatus.INFO,
                        RuleCode.NOT_EVALUATED,
                        "Inserted row; the feed does not carry this column.",
                        has_expected=False,
                    )
                    continue
                expected = expected_row[column]
                cells[column] = (
                    _cell(
                        column,
                        None,
                        actual,
                        expected,
                        CellStatus.PASS,
                        RuleCode.CORRECT_INSERT,
                        "Inserted with the value the feed carries.",
                    )
                    if eq(actual, expected)
                    else _cell(
                        column,
                        None,
                        actual,
                        expected,
                        CellStatus.FAIL,
                        RuleCode.WRONG_INSERT_VALUE,
                        f"Feed carries '{display(expected)}' but the inserted row holds "
                        f"'{display(actual)}'.",
                    )
                )
                continue

            original = before_row.get(column)
            expected = expected_row.get(column, original)
            set_by_feed = column in setters and delta_row is not None
            feed_wants_change = set_by_feed and not eq(original, expected)

            if eq(actual, expected):
                if feed_wants_change:
                    code, note = (
                        RuleCode.CORRECT_UPDATE,
                        "Updated to the value the feed carries.",
                    )
                elif set_by_feed:
                    code, note = (
                        RuleCode.CORRECT_NOOP,
                        "Feed re-sent the value the record already held; correctly left alone.",
                    )
                else:
                    code, note = (RuleCode.CORRECT_UNCHANGED, "Value correctly left unchanged.")
                cells[column] = _cell(
                    column, original, actual, expected, CellStatus.PASS, code, note
                )
                continue

            # Wrong. Which flavour of wrong?
            if feed_wants_change and eq(actual, original):
                cells[column] = _cell(
                    column,
                    original,
                    actual,
                    expected,
                    CellStatus.FAIL,
                    RuleCode.MISSING_UPDATE,
                    f"Feed carries '{display(expected)}' but the value is still "
                    f"'{display(original)}'.",
                )
            elif feed_wants_change:
                cells[column] = _cell(
                    column,
                    original,
                    actual,
                    expected,
                    CellStatus.FAIL,
                    RuleCode.WRONG_VALUE,
                    f"Feed carries '{display(expected)}' but the value is now "
                    f"'{display(actual)}'.",
                )
            else:
                status = CellStatus.FAIL if config.strict_unlisted_columns else CellStatus.WARN
                note = (
                    "Value changed but the feed re-sent the same value for this column."
                    if set_by_feed
                    else "Value changed but nothing in the feed asks for this change."
                )
                cells[column] = _cell(
                    column, original, actual, expected, status, RuleCode.UNEXPECTED_CHANGE, note
                )

        # --- last modified --------------------------------------------------------
        if config.last_modified_column:
            column = config.last_modified_column
            if not config.check_timestamp:
                cells[column] = _cell(
                    column,
                    (before_row or {}).get(column),
                    after_row.get(column),
                    None,
                    CellStatus.INFO,
                    RuleCode.NOT_EVALUATED,
                    has_expected=False,
                )
            elif row_type is RowType.INSERT_EXPECTED:
                cells[column] = _cell(
                    column,
                    None,
                    after_row.get(column),
                    None,
                    CellStatus.INFO,
                    RuleCode.NOT_EVALUATED,
                    "Inserted row; there is no previous timestamp to compare against.",
                    has_expected=False,
                )
            else:
                data_changed = any(
                    not eq(before_row.get(name), after_row.get(name))
                    for name in compare_columns
                )
                cells[column] = _evaluate_timestamp(
                    column,
                    before_row.get(column),
                    after_row.get(column),
                    row_type=row_type,
                    data_changed=data_changed,
                    config=config,
                    eq=eq,
                )

        if key in before_dupes or key in after_dupes or key in delta_dupes:
            messages.append("Key appears more than once; only the first occurrence was compared.")
            bump(issues, RuleCode.DUPLICATE_KEY.value)

        for cell in cells.values():
            if cell["code"] != RuleCode.KEY.value and cell["status"] in (
                CellStatus.FAIL.value,
                CellStatus.WARN.value,
            ):
                bump(issues, cell["code"])
            if cell["message"] and cell["status"] == CellStatus.FAIL.value:
                note = f"{cell['column']}: {cell['message']}"
                if note not in messages:
                    messages.append(note)

        bump(rows_by_type, row_type.value)
        results.append(_row(key, row_type, cells, messages))

    summary = _summarise(results, grid_columns, config, issues, rows_by_type, started, started_at)
    logger.info(
        "Validation finished: status=%s rows=%d passed=%d failed=%d warned=%d (%d ms)",
        summary["status"],
        summary["rows_total"],
        summary["rows_passed"],
        summary["rows_failed"],
        summary["rows_warned"],
        summary["duration_ms"],
    )
    return {"summary": summary, "rows": results, "columns": grid_columns}


def _row(
    key: str, row_type: RowType, cells: dict[str, dict[str, Any]], messages: list[str]
) -> dict[str, Any]:
    worst = _worst([CellStatus(c["status"]) for c in cells.values()])
    # Nothing to report is a pass; INFO is a cell-level state, not a row verdict.
    return {
        "key": key,
        "rowType": row_type.value,
        "rowStatus": (CellStatus.PASS if worst is CellStatus.INFO else worst).value,
        "cells": cells,
        "messages": messages,
    }


def _evaluate_timestamp(
    column: str,
    before_value: Any,
    after_value: Any,
    *,
    row_type: RowType,
    data_changed: bool,
    config: TestConfig,
    eq,
) -> dict[str, Any]:
    """A record that genuinely changed must be stamped; one that did not, must not."""

    should_have_moved = row_type is RowType.UPDATE_EXPECTED or data_changed
    before_ts = parse_timestamp(before_value)
    after_ts = parse_timestamp(after_value)

    if before_ts is None or after_ts is None:
        if should_have_moved and eq(before_value, after_value):
            return _cell(
                column,
                before_value,
                after_value,
                None,
                CellStatus.FAIL,
                RuleCode.TIMESTAMP_NOT_UPDATED,
                "Row changed but the last-modified value did not.",
                has_expected=False,
            )
        return _cell(
            column,
            before_value,
            after_value,
            None,
            CellStatus.WARN,
            RuleCode.TIMESTAMP_UNPARSEABLE,
            "Last-modified value could not be read as a date/time.",
            has_expected=False,
        )

    if should_have_moved:
        if after_ts > before_ts:
            return _cell(
                column,
                before_value,
                after_value,
                None,
                CellStatus.PASS,
                RuleCode.TIMESTAMP_OK,
                "Last-modified moved forward with the change.",
                has_expected=False,
            )
        if after_ts == before_ts:
            return _cell(
                column,
                before_value,
                after_value,
                None,
                CellStatus.FAIL,
                RuleCode.TIMESTAMP_NOT_UPDATED,
                "Row changed but last-modified was not bumped.",
                has_expected=False,
            )
        return _cell(
            column,
            before_value,
            after_value,
            None,
            CellStatus.FAIL,
            RuleCode.TIMESTAMP_REGRESSED,
            f"Last-modified went backwards ({display(before_value)} -> {display(after_value)}).",
            has_expected=False,
        )

    if after_ts == before_ts:
        return _cell(
            column,
            before_value,
            after_value,
            None,
            CellStatus.PASS,
            RuleCode.TIMESTAMP_OK,
            "Nothing needed to change and last-modified stayed put.",
            has_expected=False,
        )

    # The value moved without the record needing to change.
    if row_type is RowType.NOOP_EXPECTED:
        if config.allow_noop_timestamp_bump:
            return _cell(
                column,
                before_value,
                after_value,
                None,
                CellStatus.INFO,
                RuleCode.NOOP_TIMESTAMP_MOVED,
                "Feed re-sent this record unchanged; the stamp moved, which is allowed here.",
                has_expected=False,
            )
        return _cell(
            column,
            before_value,
            after_value,
            None,
            CellStatus.WARN,
            RuleCode.NOOP_TIMESTAMP_MOVED,
            "Feed re-sent this record unchanged, but the record was stamped as modified.",
            has_expected=False,
        )

    status = CellStatus.WARN if config.flag_timestamp_without_change else CellStatus.INFO
    return _cell(
        column,
        before_value,
        after_value,
        None,
        status,
        RuleCode.TIMESTAMP_MOVED_WITHOUT_CHANGE,
        "Last-modified moved even though no data changed.",
        has_expected=False,
    )


def _summarise(
    results: list[dict[str, Any]],
    columns: list[str],
    config: TestConfig,
    issues: dict[str, int],
    rows_by_type: dict[str, int],
    started: float,
    started_at: str,
) -> dict[str, Any]:
    cells_total = cells_passed = cells_failed = cells_warned = 0
    rows_passed = rows_failed = rows_warned = 0

    for row in results:
        status = row["rowStatus"]
        if status == CellStatus.FAIL.value:
            rows_failed += 1
        elif status == CellStatus.WARN.value:
            rows_warned += 1
        else:
            rows_passed += 1
        for cell in row["cells"].values():
            if cell["code"] == RuleCode.KEY.value:
                continue
            cells_total += 1
            if cell["status"] == CellStatus.PASS.value:
                cells_passed += 1
            elif cell["status"] == CellStatus.FAIL.value:
                cells_failed += 1
            elif cell["status"] == CellStatus.WARN.value:
                cells_warned += 1

    overall = "PASS"
    if rows_failed:
        overall = "FAIL"
    elif rows_warned:
        overall = "WARN"

    return {
        "started_at": started_at,
        "finished_at": utcnow(),
        "duration_ms": int((time.time() - started) * 1000),
        "status": overall,
        "rows_total": len(results),
        "rows_passed": rows_passed,
        "rows_failed": rows_failed,
        "rows_warned": rows_warned,
        "cells_total": cells_total,
        "cells_passed": cells_passed,
        "cells_failed": cells_failed,
        "cells_warned": cells_warned,
        "rows_by_type": rows_by_type,
        "issues_by_code": issues,
        "columns": columns,
        "key_columns": list(config.key_columns),
        "last_modified_column": config.last_modified_column,
        "config": config.model_dump(mode="json"),
    }
