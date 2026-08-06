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
    EXPECTED_CHANGE = "EXPECTED_CHANGE"  # key present in the delta file
    NO_CHANGE_EXPECTED = "NO_CHANGE_EXPECTED"  # key absent from the delta file
    ADDED = "ADDED"  # only in the current file
    DELETED = "DELETED"  # only in the before file
    DELTA_ORPHAN = "DELTA_ORPHAN"  # delta row whose key is in neither dataset


class RuleCode(str, Enum):
    CORRECT_UPDATE = "CORRECT_UPDATE"
    CORRECT_UNCHANGED = "CORRECT_UNCHANGED"
    MISSING_UPDATE = "MISSING_UPDATE"
    WRONG_VALUE = "WRONG_VALUE"
    UNEXPECTED_CHANGE = "UNEXPECTED_CHANGE"
    DELTA_BEFORE_VALUE_MISMATCH = "DELTA_BEFORE_VALUE_MISMATCH"
    TIMESTAMP_OK = "TIMESTAMP_OK"
    TIMESTAMP_NOT_UPDATED = "TIMESTAMP_NOT_UPDATED"
    TIMESTAMP_REGRESSED = "TIMESTAMP_REGRESSED"
    TIMESTAMP_MOVED_WITHOUT_CHANGE = "TIMESTAMP_MOVED_WITHOUT_CHANGE"
    TIMESTAMP_UNPARSEABLE = "TIMESTAMP_UNPARSEABLE"
    ROW_MISSING_IN_AFTER = "ROW_MISSING_IN_AFTER"
    ROW_ADDED_IN_AFTER = "ROW_ADDED_IN_AFTER"
    DELTA_KEY_NOT_FOUND = "DELTA_KEY_NOT_FOUND"
    DUPLICATE_KEY = "DUPLICATE_KEY"
    KEY = "KEY"


DeltaValueMode = Literal["new_value", "old_value", "presence_only"]


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

    # Delta payload semantics.
    delta_column_map: list[ColumnMapping] = Field(default_factory=list)
    delta_value_mode: DeltaValueMode = "new_value"

    # Comparison behaviour.
    case_sensitive: bool = False
    trim_whitespace: bool = True
    numeric_tolerance: float = 0.0

    # Rule toggles.
    strict_unlisted_columns: bool = True
    check_timestamp: bool = True
    flag_timestamp_without_change: bool = True
    flag_added_rows: bool = True
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
