export type FileRole = 'before' | 'after' | 'delta';
export type CellStatus = 'PASS' | 'FAIL' | 'WARN' | 'INFO';
export type RunStatus = 'PASS' | 'FAIL' | 'WARN';
export type DeltaValueMode = 'new_value' | 'old_value' | 'presence_only';

export type RowType =
  | 'EXPECTED_CHANGE'
  | 'NO_CHANGE_EXPECTED'
  | 'ADDED'
  | 'DELETED'
  | 'DELTA_ORPHAN';

export interface ColumnMapping {
  delta_column: string;
  target_column: string;
}

export interface TestConfig {
  key_columns: string[];
  delta_key_columns: string[];
  compare_columns: string[];
  ignore_columns: string[];
  last_modified_column: string | null;
  delta_column_map: ColumnMapping[];
  delta_value_mode: DeltaValueMode;
  case_sensitive: boolean;
  trim_whitespace: boolean;
  numeric_tolerance: number;
  strict_unlisted_columns: boolean;
  check_timestamp: boolean;
  flag_timestamp_without_change: boolean;
  flag_added_rows: boolean;
  flag_deleted_rows: boolean;
}

export interface DatasetSummary {
  role: FileRole;
  filename: string;
  columns: string[];
  row_count: number;
  uploaded_at: string;
  preview: Record<string, unknown>[];
}

export interface RunSummary {
  run_id: string;
  test_id: string;
  started_at: string;
  finished_at: string;
  duration_ms: number;
  status: RunStatus;
  rows_total: number;
  rows_passed: number;
  rows_failed: number;
  rows_warned: number;
  cells_total: number;
  cells_passed: number;
  cells_failed: number;
  cells_warned: number;
  rows_by_type: Record<string, number>;
  issues_by_code: Record<string, number>;
  columns: string[];
  key_columns: string[];
  last_modified_column: string | null;
  config?: TestConfig;
}

export interface ValidationTest {
  id: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
  config: TestConfig;
  datasets: Partial<Record<FileRole, DatasetSummary>>;
  last_run: RunSummary | null;
}

export interface CellResult {
  column: string;
  before: string;
  after: string;
  expected: string | null;
  changed: boolean;
  status: CellStatus;
  code: string;
  message: string;
}

export interface RunRow {
  key: string;
  rowType: RowType;
  rowStatus: RunStatus;
  cells: Record<string, CellResult>;
  messages: string[];
}

export interface RunResults {
  summary: RunSummary;
  columns: string[];
  total: number;
  rows: RunRow[];
}

export const RULE_LABELS: Record<string, string | undefined> = {
  CORRECT_UPDATE: 'Correctly updated',
  CORRECT_UNCHANGED: 'Correctly unchanged',
  MISSING_UPDATE: 'Update never applied',
  WRONG_VALUE: 'Updated to the wrong value',
  UNEXPECTED_CHANGE: 'Changed without a delta entry',
  DELTA_BEFORE_VALUE_MISMATCH: 'Delta previous value disagrees with before file',
  TIMESTAMP_OK: 'Last modified is consistent',
  TIMESTAMP_NOT_UPDATED: 'Last modified not bumped',
  TIMESTAMP_REGRESSED: 'Last modified went backwards',
  TIMESTAMP_MOVED_WITHOUT_CHANGE: 'Last modified moved without a data change',
  TIMESTAMP_UNPARSEABLE: 'Last modified is not a readable date',
  ROW_MISSING_IN_AFTER: 'Row missing from current file',
  ROW_ADDED_IN_AFTER: 'Row added in current file',
  DELTA_KEY_NOT_FOUND: 'Delta key not found in the data',
  DUPLICATE_KEY: 'Duplicate key',
  KEY: 'Key',
};

export const ROW_TYPE_LABELS: Record<string, string | undefined> = {
  EXPECTED_CHANGE: 'Change expected',
  NO_CHANGE_EXPECTED: 'No change expected',
  ADDED: 'Added row',
  DELETED: 'Deleted row',
  DELTA_ORPHAN: 'Delta orphan',
};

export const DELTA_MODE_LABELS: Record<DeltaValueMode, string> = {
  new_value: 'Delta holds the new value the current file should show',
  old_value: 'Delta holds the previous value the row moved away from',
  presence_only: 'Delta only lists which rows/columns should have moved',
};
