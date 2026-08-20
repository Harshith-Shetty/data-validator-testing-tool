"""Engine rules under upsert semantics.

The third file is a feed of records to apply, not a diff. A record in it may
update, insert, or legitimately do nothing at all.
"""

from __future__ import annotations

import pytest

from app.models import ColumnMapping, TestConfig
from app.validation.engine import ValidationError, run_validation
from app.validation.suggest import suggest_config


def dataset(columns: list[str], rows: list[dict]) -> dict:
    return {"columns": columns, "rows": rows, "row_count": len(rows), "filename": "x.csv"}


DATA_COLUMNS = ["Id", "last modified", "att1"]


def data(*rows: tuple[str, str, str]) -> dict:
    return dataset(
        DATA_COLUMNS,
        [{"Id": i, "last modified": ts, "att1": v} for i, ts, v in rows],
    )


def feed(*rows: tuple[str, str]) -> dict:
    return dataset(["Issuer", "country"], [{"Issuer": i, "country": v} for i, v in rows])


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


# --------------------------------------------------------------- the four outcomes


def test_update_noop_insert_and_missing_insert(config):
    """One feed, every outcome it can produce."""
    before = data(
        ("1", "2026-01-01 10:00:00", "uk"),
        ("2", "2026-01-01 10:00:00", "usa"),
    )
    after = data(
        ("1", "2026-01-01 10:00:00", "uk"),  # no-op, correctly untouched
        ("2", "2026-06-01 09:00:00", "france"),  # updated + stamped
        ("3", "2026-06-01 09:00:00", "japan"),  # inserted
    )
    delta = feed(("1", "uk"), ("2", "france"), ("3", "japan"), ("4", "spain"))

    rows = rows_by_key(run_validation(before, after, delta, config))

    assert rows["1"]["rowType"] == "NOOP_EXPECTED"
    assert rows["1"]["rowStatus"] == "PASS"
    assert rows["1"]["cells"]["att1"]["code"] == "CORRECT_NOOP"
    assert rows["1"]["cells"]["last modified"]["code"] == "TIMESTAMP_OK"

    assert rows["2"]["rowType"] == "UPDATE_EXPECTED"
    assert rows["2"]["rowStatus"] == "PASS"
    assert rows["2"]["cells"]["att1"]["code"] == "CORRECT_UPDATE"

    assert rows["3"]["rowType"] == "INSERT_EXPECTED"
    assert rows["3"]["rowStatus"] == "PASS"
    assert rows["3"]["cells"]["att1"]["code"] == "CORRECT_INSERT"
    # An inserted row has no previous timestamp to compare against.
    assert rows["3"]["cells"]["last modified"]["code"] == "NOT_EVALUATED"

    assert rows["4"]["rowType"] == "INSERT_EXPECTED"
    assert rows["4"]["rowStatus"] == "FAIL"
    assert rows["4"]["cells"]["att1"]["code"] == "MISSING_INSERT"


def test_noop_must_not_be_restamped(config):
    """Re-sending an identical record should not mark the record as modified."""
    before = data(("1", "2026-01-01 10:00:00", "uk"))
    after = data(("1", "2026-06-01 09:00:00", "uk"))  # value same, stamp moved
    delta = feed(("1", "uk"))

    row = rows_by_key(run_validation(before, after, delta, config))["1"]
    assert row["cells"]["att1"]["code"] == "CORRECT_NOOP"
    assert row["cells"]["last modified"]["code"] == "NOOP_TIMESTAMP_MOVED"
    assert row["cells"]["last modified"]["status"] == "WARN"
    assert row["rowStatus"] == "WARN"


def test_noop_restamp_can_be_allowed(config):
    """Systems that stamp every processed record can turn the warning off."""
    config.allow_noop_timestamp_bump = True
    before = data(("1", "2026-01-01 10:00:00", "uk"))
    after = data(("1", "2026-06-01 09:00:00", "uk"))
    delta = feed(("1", "uk"))

    row = rows_by_key(run_validation(before, after, delta, config))["1"]
    assert row["rowStatus"] == "PASS"


def test_insert_with_the_wrong_value(config):
    before = data(("1", "2026-01-01 10:00:00", "uk"))
    after = data(("1", "2026-01-01 10:00:00", "uk"), ("2", "2026-06-01 09:00:00", "brazil"))
    delta = feed(("1", "uk"), ("2", "japan"))

    row = rows_by_key(run_validation(before, after, delta, config))["2"]
    assert row["cells"]["att1"]["code"] == "WRONG_INSERT_VALUE"
    assert row["rowStatus"] == "FAIL"


def test_row_appearing_with_nothing_asking_for_it(config):
    before = data(("1", "2026-01-01 10:00:00", "uk"))
    after = data(("1", "2026-01-01 10:00:00", "uk"), ("9", "2026-06-01 09:00:00", "peru"))
    delta = feed(("1", "uk"))

    row = rows_by_key(run_validation(before, after, delta, config))["9"]
    assert row["rowType"] == "UNEXPECTED_INSERT"
    assert row["rowStatus"] == "FAIL"

    config.flag_unexpected_inserts = False
    relaxed = rows_by_key(run_validation(before, after, delta, config))["9"]
    assert relaxed["rowStatus"] == "PASS"


# ------------------------------------------------------------------- update rules


def test_update_that_never_landed(config):
    before = data(("1", "2026-01-01 10:00:00", "uk"))
    after = data(("1", "2026-01-01 10:00:00", "uk"))
    delta = feed(("1", "india"))

    row = rows_by_key(run_validation(before, after, delta, config))["1"]
    assert row["cells"]["att1"]["code"] == "MISSING_UPDATE"
    assert row["cells"]["last modified"]["code"] == "TIMESTAMP_NOT_UPDATED"


def test_update_that_landed_wrong(config):
    before = data(("1", "2026-01-01 10:00:00", "uk"))
    after = data(("1", "2026-06-01 09:00:00", "brazil"))
    delta = feed(("1", "india"))

    cell = rows_by_key(run_validation(before, after, delta, config))["1"]["cells"]["att1"]
    assert cell["code"] == "WRONG_VALUE"
    assert cell["expected"] == "india"


def test_value_moving_with_nothing_asking_for_it(config):
    before = data(("1", "2026-01-01 10:00:00", "uk"))
    after = data(("1", "2026-06-01 09:00:00", "france"))
    delta = feed()  # empty feed: nothing should have moved

    row = rows_by_key(run_validation(before, after, delta, config))["1"]
    assert row["rowType"] == "UNTOUCHED"
    assert row["cells"]["att1"]["code"] == "UNEXPECTED_CHANGE"

    config.strict_unlisted_columns = False
    relaxed = rows_by_key(run_validation(before, after, delta, config))["1"]
    assert relaxed["cells"]["att1"]["status"] == "WARN"


def test_feed_resent_same_value_but_data_moved_anyway(config):
    """The original worked example: feed says 'uk', record becomes 'india'."""
    before = data(("1", "2026-08-02 12:23:00", "uk"))
    after = data(("1", "2026-08-01 14:02:00", "india"))
    delta = feed(("1", "uk"))

    row = rows_by_key(run_validation(before, after, delta, config))["1"]
    assert row["cells"]["att1"]["code"] == "UNEXPECTED_CHANGE"
    assert row["cells"]["last modified"]["code"] == "TIMESTAMP_REGRESSED"
    assert row["rowStatus"] == "FAIL"


def test_deleted_row_is_flagged(config):
    before = data(("1", "2026-01-01 10:00:00", "uk"), ("2", "2026-01-01 10:00:00", "usa"))
    after = data(("1", "2026-01-01 10:00:00", "uk"))
    delta = feed()

    row = rows_by_key(run_validation(before, after, delta, config))["2"]
    assert row["rowType"] == "DELETED"
    assert row["cells"]["att1"]["code"] == "ROW_MISSING_IN_AFTER"
    assert row["rowStatus"] == "FAIL"


# ----------------------------------------------------------------- column handling


def test_columns_the_feed_does_not_carry_must_stay_put(config):
    columns = ["Id", "last modified", "att1", "att2"]
    before = dataset(columns, [{"Id": "1", "last modified": "2026-01-01 10:00:00", "att1": "uk", "att2": "keep"}])
    after = dataset(columns, [{"Id": "1", "last modified": "2026-06-01 09:00:00", "att1": "india", "att2": "moved"}])
    config.compare_columns = ["att1", "att2"]
    delta = feed(("1", "india"))

    cells = rows_by_key(run_validation(before, after, delta, config))["1"]["cells"]
    assert cells["att1"]["code"] == "CORRECT_UPDATE"
    assert cells["att2"]["code"] == "UNEXPECTED_CHANGE"


def test_inserted_row_columns_the_feed_cannot_speak_for(config):
    columns = ["Id", "last modified", "att1", "att2"]
    before = dataset(columns, [])
    after = dataset(columns, [{"Id": "1", "last modified": "2026-06-01 09:00:00", "att1": "uk", "att2": "whatever"}])
    config.compare_columns = ["att1", "att2"]
    delta = feed(("1", "uk"))

    cells = rows_by_key(run_validation(before, after, delta, config))["1"]["cells"]
    assert cells["att1"]["code"] == "CORRECT_INSERT"
    # Nothing in the three files says what att2 should hold on a new record.
    assert cells["att2"]["code"] == "NOT_EVALUATED"
    assert cells["att2"]["status"] == "INFO"


def test_case_and_whitespace_insensitive_by_default(config):
    before = data(("1", "2026-01-01 10:00:00", "usa"))
    after = data(("1", "2026-01-01 10:00:00", "  USA  "))
    delta = feed()

    assert rows_by_key(run_validation(before, after, delta, config))["1"]["rowStatus"] == "PASS"

    config.case_sensitive = True
    strict = rows_by_key(run_validation(before, after, delta, config))["1"]
    assert strict["cells"]["att1"]["code"] == "UNEXPECTED_CHANGE"


def test_numeric_values_compare_numerically(config):
    before = dataset(["Id", "amount"], [{"Id": "1", "amount": "10"}])
    after = dataset(["Id", "amount"], [{"Id": "1", "amount": "10.0"}])
    config.compare_columns = ["amount"]
    config.last_modified_column = None
    result = run_validation(before, after, feed(), config)
    assert rows_by_key(result)["1"]["cells"]["amount"]["status"] == "PASS"


def test_key_columns_are_required():
    with pytest.raises(ValidationError):
        run_validation(data(("1", "x", "y")), data(("1", "x", "y")), feed(), TestConfig())


# -------------------------------------------------------------------- the summary


def test_summary_counts_and_overall_status(config):
    before = data(("1", "2026-01-01 10:00:00", "uk"), ("2", "2026-01-01 10:00:00", "usa"))
    after = data(("1", "2026-01-01 10:00:00", "uk"), ("2", "2026-01-01 10:00:00", "usa"))
    delta = feed(("1", "uk"), ("2", "france"))  # row 2's update never landed

    result = run_validation(before, after, delta, config)
    summary = result["summary"]
    assert summary["status"] == "FAIL"
    assert summary["rows_passed"] == 1
    assert summary["rows_failed"] == 1
    assert summary["issues_by_code"]["MISSING_UPDATE"] == 1
    assert summary["rows_by_type"] == {"NOOP_EXPECTED": 1, "UPDATE_EXPECTED": 1}


def test_clean_run_passes(config):
    before = data(("1", "2026-01-01 10:00:00", "uk"))
    after = data(("1", "2026-06-01 09:00:00", "india"), ("2", "2026-06-01 09:00:00", "japan"))
    delta = feed(("1", "india"), ("2", "japan"))

    summary = run_validation(before, after, delta, config)["summary"]
    assert summary["status"] == "PASS"
    assert summary["rows_failed"] == 0


def test_suggest_config_still_maps_the_example():
    before = data(("1", "2026-08-02 12:23:00", "uk"), ("2", "2026-05-01 15:56:00", "usa"))
    after = data(("1", "2026-08-01 14:02:00", "india"), ("2", "2026-05-01 15:56:00", "usa"))
    delta = feed(("1", "uk"))

    suggested = suggest_config(before, after, delta)
    assert suggested.key_columns == ["Id"]
    assert suggested.delta_key_columns == ["Issuer"]
    assert suggested.last_modified_column == "last modified"
    assert [(m.delta_column, m.target_column) for m in suggested.delta_column_map] == [
        ("country", "att1")
    ]
