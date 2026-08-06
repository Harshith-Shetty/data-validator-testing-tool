"""Data capture validation engine.

Given three datasets — the state *before* a capture run, the *current* state
after it, and the *delta* describing what was supposed to change — the engine
answers one question per cell: was this cell changed the way it should have
been?

Cell verdicts
-------------
PASS  the cell is exactly where it should be (correctly updated, or correctly
      left alone)
FAIL  the cell is wrong (an expected update did not land, landed with the wrong
      value, or a value moved that nobody asked to move)
WARN  suspicious but not provably wrong (e.g. the delta's "before" value does
      not match the before file)
INFO  not evaluated (key columns, columns absent from one of the files)

A row's verdict is the worst verdict among its cells, and the run's verdict is
the worst verdict among its rows.
"""

from __future__ import annotations

import time
from typing import Any

from ..models import CellStatus, RowType, RuleCode, TestConfig, utcnow
from .compare import display, key_of, parse_timestamp, values_equal

_SEVERITY = {CellStatus.INFO: 0, CellStatus.PASS: 1, CellStatus.WARN: 2, CellStatus.FAIL: 3}


def _worst(statuses: list[CellStatus]) -> CellStatus:
    return max(statuses, key=lambda s: _SEVERITY[s], default=CellStatus.INFO)


class ValidationError(ValueError):
    """Raised when the configuration cannot be applied to the datasets."""


def _index_rows(
    rows: list[dict[str, Any]], key_columns: list[str], *, case_sensitive: bool
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Index rows by key, reporting keys that appear more than once."""
    index: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for row in rows:
        key = key_of(row, key_columns, case_sensitive=case_sensitive)
        if key in index:
            duplicates.append(key)
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
) -> dict[str, Any]:
    return {
        "column": column,
        "before": display(before),
        "after": display(after),
        "expected": None if expected is None else display(expected),
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

    if not config.key_columns:
        raise ValidationError("At least one key column is required.")
    delta_keys = config.delta_key_columns or config.key_columns
    if len(delta_keys) != len(config.key_columns):
        raise ValidationError("Delta key columns must line up one-to-one with the key columns.")

    cs = config.case_sensitive
    eq = lambda a, b: values_equal(  # noqa: E731 - local shorthand keeps the rules readable
        a,
        b,
        trim=config.trim_whitespace,
        case_sensitive=cs,
        numeric_tolerance=config.numeric_tolerance,
    )

    before_rows, after_rows, delta_rows = before["rows"], after["rows"], delta["rows"]
    before_index, before_dupes = _index_rows(before_rows, config.key_columns, case_sensitive=cs)
    after_index, after_dupes = _index_rows(after_rows, config.key_columns, case_sensitive=cs)
    delta_index, delta_dupes = _index_rows(delta_rows, delta_keys, case_sensitive=cs)

    compare_columns = _resolve_compare_columns(config, before["columns"], after["columns"])
    mapping = config.mapping_dict()
    # Delta columns that carry a payload (everything that is not part of the key).
    mapped_targets = {
        target for source, target in mapping.items() if source not in delta_keys and target
    }

    grid_columns = list(config.key_columns) + compare_columns
    if config.last_modified_column:
        grid_columns.append(config.last_modified_column)

    results: list[dict[str, Any]] = []
    issues: dict[str, int] = {}
    rows_by_type: dict[str, int] = {}

    def bump(counter: dict[str, int], code: str) -> None:
        counter[code] = counter.get(code, 0) + 1

    all_keys = list(dict.fromkeys(list(before_index) + list(after_index)))

    for key in all_keys:
        before_row = before_index.get(key)
        after_row = after_index.get(key)
        delta_row = delta_index.get(key)

        if before_row is None:
            row_type = RowType.ADDED
        elif after_row is None:
            row_type = RowType.DELETED
        elif delta_row is not None:
            row_type = RowType.EXPECTED_CHANGE
        else:
            row_type = RowType.NO_CHANGE_EXPECTED

        cells: dict[str, dict[str, Any]] = {}
        messages: list[str] = []
        source = after_row if after_row is not None else before_row

        for column in config.key_columns:
            cells[column] = _cell(
                column, source.get(column), source.get(column), None, CellStatus.INFO, RuleCode.KEY
            )

        # ------------------------------------------------ rows that only exist on one side
        if row_type in (RowType.ADDED, RowType.DELETED):
            missing_code = (
                RuleCode.ROW_ADDED_IN_AFTER
                if row_type is RowType.ADDED
                else RuleCode.ROW_MISSING_IN_AFTER
            )
            flagged = (
                config.flag_added_rows if row_type is RowType.ADDED else config.flag_deleted_rows
            )
            status = CellStatus.FAIL if flagged else CellStatus.INFO
            note = (
                "Row is in the current file but not in the before file."
                if row_type is RowType.ADDED
                else "Row is in the before file but missing from the current file."
            )
            messages.append(note)
            bump(issues, missing_code.value)
            for column in compare_columns + (
                [config.last_modified_column] if config.last_modified_column else []
            ):
                cells[column] = _cell(
                    column,
                    (before_row or {}).get(column),
                    (after_row or {}).get(column),
                    None,
                    status,
                    missing_code,
                    note,
                )
            bump(rows_by_type, row_type.value)
            results.append(
                {
                    "key": key,
                    "rowType": row_type.value,
                    "rowStatus": _worst([CellStatus(c["status"]) for c in cells.values()]).value,
                    "cells": cells,
                    "messages": messages,
                }
            )
            continue

        # -------------------------------------------------------------- data columns
        data_changed = False
        for column in compare_columns:
            b_val, a_val = before_row.get(column), after_row.get(column)
            changed = not eq(b_val, a_val)
            data_changed = data_changed or changed
            is_targeted = row_type is RowType.EXPECTED_CHANGE and column in mapped_targets

            if is_targeted:
                delta_source = next(
                    src for src, tgt in mapping.items() if tgt == column and src not in delta_keys
                )
                delta_value = delta_row.get(delta_source)
                cells[column] = _evaluate_expected_change(
                    column, b_val, a_val, delta_value, changed, config, eq
                )
            elif row_type is RowType.EXPECTED_CHANGE and not mapped_targets:
                # No delta payload mapped at all: the delta only says "this row
                # should have moved", so any change in any column counts.
                cells[column] = (
                    _cell(
                        column,
                        b_val,
                        a_val,
                        None,
                        CellStatus.PASS,
                        RuleCode.CORRECT_UPDATE,
                        "Value was updated as the delta requires.",
                    )
                    if changed
                    else _cell(
                        column,
                        b_val,
                        a_val,
                        None,
                        CellStatus.INFO,
                        RuleCode.CORRECT_UNCHANGED,
                        "",
                    )
                )
            elif changed:
                status = CellStatus.FAIL if config.strict_unlisted_columns else CellStatus.WARN
                note = (
                    "Value changed but the delta file does not ask for this change."
                    if row_type is RowType.NO_CHANGE_EXPECTED
                    else "Value changed but the delta file only lists other columns for this row."
                )
                cells[column] = _cell(
                    column, b_val, a_val, b_val, status, RuleCode.UNEXPECTED_CHANGE, note
                )
            else:
                cells[column] = _cell(
                    column,
                    b_val,
                    a_val,
                    None,
                    CellStatus.PASS,
                    RuleCode.CORRECT_UNCHANGED,
                    "Value correctly left unchanged.",
                )

        # ---------------------------------------------------------- last modified column
        if config.last_modified_column and config.check_timestamp:
            cells[config.last_modified_column] = _evaluate_timestamp(
                config.last_modified_column,
                before_row.get(config.last_modified_column),
                after_row.get(config.last_modified_column),
                should_have_changed=row_type is RowType.EXPECTED_CHANGE or data_changed,
                config=config,
                eq=eq,
            )
        elif config.last_modified_column:
            column = config.last_modified_column
            cells[column] = _cell(
                column,
                before_row.get(column),
                after_row.get(column),
                None,
                CellStatus.INFO,
                RuleCode.TIMESTAMP_OK,
            )

        if key in before_dupes or key in after_dupes or key in delta_dupes:
            messages.append("Key appears more than once; only the first occurrence was compared.")
            bump(issues, RuleCode.DUPLICATE_KEY.value)

        for cell in cells.values():
            if cell["code"] not in (RuleCode.KEY.value,) and cell["status"] in (
                CellStatus.FAIL.value,
                CellStatus.WARN.value,
            ):
                bump(issues, cell["code"])
            if cell["message"] and cell["message"] not in messages and cell["status"] == "FAIL":
                messages.append(f"{cell['column']}: {cell['message']}")

        bump(rows_by_type, row_type.value)
        results.append(
            {
                "key": key,
                "rowType": row_type.value,
                "rowStatus": _worst([CellStatus(c["status"]) for c in cells.values()]).value,
                "cells": cells,
                "messages": messages,
            }
        )

    # -------------------------------------------------- delta rows matching nothing at all
    for key, delta_row in delta_index.items():
        if key in before_index or key in after_index:
            continue
        note = "Delta row refers to a key that exists in neither the before nor the current file."
        cells = {
            column: _cell(
                column,
                None,
                None,
                delta_row.get(src) if (src := _source_for(mapping, delta_keys, column)) else None,
                CellStatus.FAIL,
                RuleCode.DELTA_KEY_NOT_FOUND,
                note,
            )
            for column in grid_columns
        }
        for idx, column in enumerate(config.key_columns):
            cells[column] = _cell(
                column,
                None,
                delta_row.get(delta_keys[idx]),
                None,
                CellStatus.FAIL,
                RuleCode.DELTA_KEY_NOT_FOUND,
                note,
            )
        bump(issues, RuleCode.DELTA_KEY_NOT_FOUND.value)
        bump(rows_by_type, RowType.DELTA_ORPHAN.value)
        results.append(
            {
                "key": key,
                "rowType": RowType.DELTA_ORPHAN.value,
                "rowStatus": CellStatus.FAIL.value,
                "cells": cells,
                "messages": [note],
            }
        )

    summary = _summarise(results, grid_columns, config, issues, rows_by_type, started, started_at)
    return {"summary": summary, "rows": results, "columns": grid_columns}


def _source_for(mapping: dict[str, str], delta_keys: list[str], column: str) -> str | None:
    for src, tgt in mapping.items():
        if tgt == column and src not in delta_keys:
            return src
    return None


def _evaluate_expected_change(
    column: str,
    before_value: Any,
    after_value: Any,
    delta_value: Any,
    changed: bool,
    config: TestConfig,
    eq,
) -> dict[str, Any]:
    """Rules for a cell the delta file explicitly asks to change."""

    if config.delta_value_mode == "new_value":
        if eq(after_value, delta_value):
            return _cell(
                column,
                before_value,
                after_value,
                delta_value,
                CellStatus.PASS,
                RuleCode.CORRECT_UPDATE,
                "Updated to the value requested by the delta file.",
            )
        if not changed:
            return _cell(
                column,
                before_value,
                after_value,
                delta_value,
                CellStatus.FAIL,
                RuleCode.MISSING_UPDATE,
                f"Delta asks for '{display(delta_value)}' but the value is still "
                f"'{display(before_value)}'.",
            )
        return _cell(
            column,
            before_value,
            after_value,
            delta_value,
            CellStatus.FAIL,
            RuleCode.WRONG_VALUE,
            f"Delta asks for '{display(delta_value)}' but the value is now "
            f"'{display(after_value)}'.",
        )

    if config.delta_value_mode == "old_value":
        if not changed:
            return _cell(
                column,
                before_value,
                after_value,
                None,
                CellStatus.FAIL,
                RuleCode.MISSING_UPDATE,
                "Delta lists this cell as changed but it still holds its previous value.",
            )
        if not eq(before_value, delta_value):
            return _cell(
                column,
                before_value,
                after_value,
                delta_value,
                CellStatus.WARN,
                RuleCode.DELTA_BEFORE_VALUE_MISMATCH,
                f"Value was updated, but the delta's previous value "
                f"'{display(delta_value)}' does not match the before file "
                f"'{display(before_value)}'.",
            )
        return _cell(
            column,
            before_value,
            after_value,
            None,
            CellStatus.PASS,
            RuleCode.CORRECT_UPDATE,
            "Updated away from the previous value recorded in the delta file.",
        )

    # presence_only
    if changed:
        return _cell(
            column,
            before_value,
            after_value,
            None,
            CellStatus.PASS,
            RuleCode.CORRECT_UPDATE,
            "Value was updated as the delta requires.",
        )
    return _cell(
        column,
        before_value,
        after_value,
        None,
        CellStatus.FAIL,
        RuleCode.MISSING_UPDATE,
        "Delta lists this cell as changed but the value is unchanged.",
    )


def _evaluate_timestamp(
    column: str,
    before_value: Any,
    after_value: Any,
    *,
    should_have_changed: bool,
    config: TestConfig,
    eq,
) -> dict[str, Any]:
    before_ts = parse_timestamp(before_value)
    after_ts = parse_timestamp(after_value)

    if before_ts is None or after_ts is None:
        equal = eq(before_value, after_value)
        if should_have_changed and equal:
            return _cell(
                column,
                before_value,
                after_value,
                None,
                CellStatus.FAIL,
                RuleCode.TIMESTAMP_NOT_UPDATED,
                "Row changed but the last-modified value did not.",
            )
        return _cell(
            column,
            before_value,
            after_value,
            None,
            CellStatus.WARN,
            RuleCode.TIMESTAMP_UNPARSEABLE,
            "Last-modified value could not be read as a date/time.",
        )

    if should_have_changed:
        if after_ts > before_ts:
            return _cell(
                column,
                before_value,
                after_value,
                None,
                CellStatus.PASS,
                RuleCode.TIMESTAMP_OK,
                "Last-modified moved forward with the change.",
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
            )
        return _cell(
            column,
            before_value,
            after_value,
            None,
            CellStatus.FAIL,
            RuleCode.TIMESTAMP_REGRESSED,
            f"Last-modified went backwards ({display(before_value)} -> {display(after_value)}).",
        )

    if after_ts == before_ts:
        return _cell(
            column,
            before_value,
            after_value,
            None,
            CellStatus.PASS,
            RuleCode.TIMESTAMP_OK,
            "Row did not change and last-modified stayed put.",
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
