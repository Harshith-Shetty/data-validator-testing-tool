"""Engine rules, driven from the worked example in the project README."""

from __future__ import annotations

import pytest

from app.models import ColumnMapping, TestConfig
from app.validation.engine import ValidationError, run_validation
from app.validation.suggest import suggest_config


def dataset(columns: list[str], rows: list[dict]) -> dict:
    return {"columns": columns, "rows": rows, "row_count": len(rows), "filename": "x.csv"}


DATA_COLUMNS = ["Id", "last modified", "att1"]


@pytest.fixture
def before() -> dict:
    return dataset(
        DATA_COLUMNS,
        [
            {"Id": "1", "last modified": "2026-08-02 12:23:00", "att1": "uk"},
            {"Id": "2", "last modified": "2026-05-01 15:56:00", "att1": "usa"},
            {"Id": "3", "last modified": "2026-04-28 06:45:00", "att1": "Australia"},
        ],
    )


@pytest.fixture
def after() -> dict:
    return dataset(
        DATA_COLUMNS,
        [
            {"Id": "1", "last modified": "2026-08-01 14:02:00", "att1": "india"},
            {"Id": "2", "last modified": "2026-05-01 15:56:00", "att1": "usa"},
            {"Id": "3", "last modified": "2026-08-01 14:02:00", "att1": "usa"},
        ],
    )


@pytest.fixture
def delta() -> dict:
    return dataset(
        ["Issuer", "country"],
        [{"Issuer": "1", "country": "uk"}, {"Issuer": "3", "country": "usa"}],
    )


@pytest.fixture
def config() -> TestConfig:
    return TestConfig(
        key_columns=["Id"],
        delta_key_columns=["Issuer"],
        last_modified_column="last modified",
        compare_columns=["att1"],
        delta_column_map=[ColumnMapping(delta_column="country", target_column="att1")],
    )


def rows_by_key(result: dict) -> dict[str, dict]:
    return {row["key"]: row for row in result["rows"]}


def test_worked_example(before, after, delta, config):
    result = run_validation(before, after, delta, config)
    rows = rows_by_key(result)

    # Row 1: delta asked for 'uk', capture wrote 'india', and the timestamp went backwards.
    assert rows["1"]["cells"]["att1"]["status"] == "FAIL"
    assert rows["1"]["cells"]["att1"]["code"] == "WRONG_VALUE"
    assert rows["1"]["cells"]["last modified"]["code"] == "TIMESTAMP_REGRESSED"
    assert rows["1"]["rowStatus"] == "FAIL"

    # Row 2: not in the delta and untouched -> everything green.
    assert rows["2"]["cells"]["att1"]["status"] == "PASS"
    assert rows["2"]["cells"]["last modified"]["status"] == "PASS"
    assert rows["2"]["rowStatus"] == "PASS"

    # Row 3: updated to the requested value with a bumped timestamp.
    assert rows["3"]["cells"]["att1"]["status"] == "PASS"
    assert rows["3"]["cells"]["att1"]["code"] == "CORRECT_UPDATE"
    assert rows["3"]["cells"]["last modified"]["status"] == "PASS"
    assert rows["3"]["rowStatus"] == "PASS"

    summary = result["summary"]
    assert summary["status"] == "FAIL"
    assert (summary["rows_failed"], summary["rows_passed"]) == (1, 2)
    assert summary["cells_failed"] == 2


def test_missing_update_is_flagged(before, after, delta, config):
    after["rows"][2]["att1"] = "Australia"  # capture never applied the change
    after["rows"][2]["last modified"] = "2026-04-28 06:45:00"
    result = run_validation(before, after, delta, config)
    cell = rows_by_key(result)["3"]["cells"]["att1"]
    assert (cell["status"], cell["code"]) == ("FAIL", "MISSING_UPDATE")
    assert rows_by_key(result)["3"]["cells"]["last modified"]["code"] == "TIMESTAMP_NOT_UPDATED"


def test_unexpected_change_is_flagged(before, after, delta, config):
    after["rows"][1]["att1"] = "france"  # row 2 is not in the delta
    result = run_validation(before, after, delta, config)
    cell = rows_by_key(result)["2"]["cells"]["att1"]
    assert (cell["status"], cell["code"]) == ("FAIL", "UNEXPECTED_CHANGE")


def test_unexpected_change_downgraded_to_warning(before, after, delta, config):
    config.strict_unlisted_columns = False
    after["rows"][1]["att1"] = "france"
    result = run_validation(before, after, delta, config)
    assert rows_by_key(result)["2"]["cells"]["att1"]["status"] == "WARN"


def test_timestamp_moved_without_data_change(before, after, delta, config):
    after["rows"][1]["last modified"] = "2026-08-05 09:00:00"
    result = run_validation(before, after, delta, config)
    cell = rows_by_key(result)["2"]["cells"]["last modified"]
    assert (cell["status"], cell["code"]) == ("WARN", "TIMESTAMP_MOVED_WITHOUT_CHANGE")
    assert result["summary"]["status"] == "FAIL"  # row 1 still fails


def test_added_and_deleted_rows(before, after, delta, config):
    after["rows"].append({"Id": "4", "last modified": "2026-08-05 09:00:00", "att1": "japan"})
    del before["rows"][1]
    del after["rows"][1]
    result = run_validation(before, after, delta, config)
    rows = rows_by_key(result)
    assert rows["4"]["rowType"] == "ADDED"
    assert rows["4"]["rowStatus"] == "FAIL"
    assert result["summary"]["issues_by_code"]["ROW_ADDED_IN_AFTER"] == 1


def test_deleted_row_detected(before, after, delta, config):
    del after["rows"][1]
    result = run_validation(before, after, delta, config)
    assert rows_by_key(result)["2"]["rowType"] == "DELETED"
    assert result["summary"]["issues_by_code"]["ROW_MISSING_IN_AFTER"] == 1


def test_delta_orphan(before, after, delta, config):
    delta["rows"].append({"Issuer": "99", "country": "spain"})
    result = run_validation(before, after, delta, config)
    orphan = rows_by_key(result)["99"]
    assert orphan["rowType"] == "DELTA_ORPHAN"
    assert orphan["rowStatus"] == "FAIL"


def test_old_value_mode(before, after, delta, config):
    """In old-value mode the delta carries the previous value, not the new one."""
    config.delta_value_mode = "old_value"
    result = run_validation(before, after, delta, config)
    rows = rows_by_key(result)
    # Row 1 moved away from 'uk', which is what the delta recorded -> correct.
    assert rows["1"]["cells"]["att1"]["code"] == "CORRECT_UPDATE"
    # Row 3's delta says the old value was 'usa' but the before file says 'Australia'.
    assert rows["3"]["cells"]["att1"]["code"] == "DELTA_BEFORE_VALUE_MISMATCH"
    assert rows["3"]["cells"]["att1"]["status"] == "WARN"


def test_presence_only_mode(before, after, delta, config):
    config.delta_value_mode = "presence_only"
    result = run_validation(before, after, delta, config)
    rows = rows_by_key(result)
    assert rows["1"]["cells"]["att1"]["status"] == "PASS"  # it changed; value not checked
    assert rows["3"]["cells"]["att1"]["status"] == "PASS"


def test_case_and_whitespace_insensitive_by_default(before, after, delta, config):
    after["rows"][1]["att1"] = "  USA  "
    result = run_validation(before, after, delta, config)
    assert rows_by_key(result)["2"]["cells"]["att1"]["status"] == "PASS"

    config.case_sensitive = True
    strict = run_validation(before, after, delta, config)
    assert rows_by_key(strict)["2"]["cells"]["att1"]["code"] == "UNEXPECTED_CHANGE"


def test_numeric_values_compare_numerically(config):
    before = dataset(["Id", "amount"], [{"Id": "1", "amount": "10"}])
    after = dataset(["Id", "amount"], [{"Id": "1", "amount": "10.0"}])
    delta = dataset(["Issuer", "country"], [])
    config.compare_columns = ["amount"]
    config.last_modified_column = None
    result = run_validation(before, after, delta, config)
    assert rows_by_key(result)["1"]["cells"]["amount"]["status"] == "PASS"


def test_key_columns_are_required(before, after, delta):
    with pytest.raises(ValidationError):
        run_validation(before, after, delta, TestConfig())


def test_suggest_config_matches_the_example(before, after, delta):
    suggested = suggest_config(before, after, delta)
    assert suggested.key_columns == ["Id"]
    assert suggested.delta_key_columns == ["Issuer"]
    assert suggested.last_modified_column == "last modified"
    assert suggested.compare_columns == ["att1"]
    assert [(m.delta_column, m.target_column) for m in suggested.delta_column_map] == [
        ("country", "att1")
    ]
