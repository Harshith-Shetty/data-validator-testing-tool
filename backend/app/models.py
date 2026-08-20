"""Pydantic models shared by the API and the validation engine."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class FileRole(str, Enum):
    BEFORE = "before"
    AFTER = "after"
    DELTA = "delta"


class CellStatus(str, Enum):
    """Drives the colour of a cell in the results grid."""

    PASS = "PASS"  # green
    FAIL = "FAIL"  # red
    WARN = "WARN"  # amber
    INFO = "INFO"  # neutral / not evaluated


class RowType(str, Enum):
    """What the delta file implies should have happened to this row."""

    UPDATE_EXPECTED = "UPDATE_EXPECTED"  # delta carries values that differ from before
    NOOP_EXPECTED = "NOOP_EXPECTED"  # delta restates what the row already held
    INSERT_EXPECTED = "INSERT_EXPECTED"  # delta key is new to the data
    UNTOUCHED = "UNTOUCHED"  # delta says nothing about this row
    UNEXPECTED_INSERT = "UNEXPECTED_INSERT"  # row appeared with nothing asking for it
    DELETED = "DELETED"  # row vanished from the current file


class RuleCode(str, Enum):
    # Passing
    CORRECT_UPDATE = "CORRECT_UPDATE"
    CORRECT_NOOP = "CORRECT_NOOP"
    CORRECT_UNCHANGED = "CORRECT_UNCHANGED"
    CORRECT_INSERT = "CORRECT_INSERT"
    TIMESTAMP_OK = "TIMESTAMP_OK"

    # Failing
    MISSING_UPDATE = "MISSING_UPDATE"
    WRONG_VALUE = "WRONG_VALUE"
    UNEXPECTED_CHANGE = "UNEXPECTED_CHANGE"
    MISSING_INSERT = "MISSING_INSERT"
    WRONG_INSERT_VALUE = "WRONG_INSERT_VALUE"
    UNEXPECTED_INSERT = "UNEXPECTED_INSERT"
    ROW_MISSING_IN_AFTER = "ROW_MISSING_IN_AFTER"
    TIMESTAMP_NOT_UPDATED = "TIMESTAMP_NOT_UPDATED"
    TIMESTAMP_REGRESSED = "TIMESTAMP_REGRESSED"

    # Suspicious
    NOOP_TIMESTAMP_MOVED = "NOOP_TIMESTAMP_MOVED"
    TIMESTAMP_MOVED_WITHOUT_CHANGE = "TIMESTAMP_MOVED_WITHOUT_CHANGE"
    TIMESTAMP_UNPARSEABLE = "TIMESTAMP_UNPARSEABLE"
    DUPLICATE_KEY = "DUPLICATE_KEY"

    # Informational
    KEY = "KEY"
    NOT_EVALUATED = "NOT_EVALUATED"


class ColumnMapping(BaseModel):
    """Maps a column of the delta file onto a column of the before/current data."""

    delta_column: str
    target_column: str


class TestConfig(BaseModel):
    # How rows are matched across the three files.
    key_columns: list[str] = Field(default_factory=list)
    delta_key_columns: list[str] = Field(default_factory=list)

    # Which data columns take part in the comparison. Empty means "every common
    # column that is neither a key nor ignored".
    compare_columns: list[str] = Field(default_factory=list)
    ignore_columns: list[str] = Field(default_factory=list)

    # Optional "last modified" column that must move when a row changes.
    last_modified_column: str | None = None

    # Which delta columns carry values, and which data column each one sets.
    delta_column_map: list[ColumnMapping] = Field(default_factory=list)

    # Comparison behaviour.
    case_sensitive: bool = False
    trim_whitespace: bool = True
    numeric_tolerance: float = 0.0

    # Rule toggles.
    strict_unlisted_columns: bool = True
    check_timestamp: bool = True
    # A record the feed re-sent unchanged should not have been touched at all.
    allow_noop_timestamp_bump: bool = False
    flag_timestamp_without_change: bool = True
    flag_unexpected_inserts: bool = True
    flag_deleted_rows: bool = True

    def mapping_dict(self) -> dict[str, str]:
        return {m.delta_column: m.target_column for m in self.delta_column_map}


class TestCreate(BaseModel):
    name: str
    description: str = ""


class TestUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class DatasetSummary(BaseModel):
    role: FileRole
    filename: str
    columns: list[str]
    row_count: int
    uploaded_at: str
    preview: list[dict[str, Any]] = Field(default_factory=list)


class RunSummary(BaseModel):
    run_id: str
    test_id: str
    started_at: str
    finished_at: str
    duration_ms: int
    status: Literal["PASS", "FAIL", "WARN"]
    rows_total: int
    rows_passed: int
    rows_failed: int
    rows_warned: int
    cells_total: int
    cells_passed: int
    cells_failed: int
    cells_warned: int
    rows_by_type: dict[str, int] = Field(default_factory=dict)
    issues_by_code: dict[str, int] = Field(default_factory=dict)
    columns: list[str] = Field(default_factory=list)
    key_columns: list[str] = Field(default_factory=list)
    last_modified_column: str | None = None
    config: TestConfig | None = None


class ValidationTest(BaseModel):
    id: str
    name: str
    description: str = ""
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)
    config: TestConfig = Field(default_factory=TestConfig)
    datasets: dict[str, DatasetSummary] = Field(default_factory=dict)
    last_run: RunSummary | None = None
