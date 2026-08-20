export type FileRole = 'before' | 'after' | 'delta';
export type CellStatus = 'PASS' | 'FAIL' | 'WARN' | 'INFO';
export type RunStatus = 'PASS' | 'FAIL' | 'WARN';

export type RowType =
  | 'UPDATE_EXPECTED'
  | 'NOOP_EXPECTED'
  | 'INSERT_EXPECTED'
  | 'UNTOUCHED'
  | 'UNEXPECTED_INSERT'
  | 'DELETED';

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
  case_sensitive: boolean;
  trim_whitespace: boolean;
  numeric_tolerance: number;
  strict_unlisted_columns: boolean;
  check_timestamp: boolean;
  allow_noop_timestamp_bump: boolean;
  flag_timestamp_without_change: boolean;
  flag_unexpected_inserts: boolean;
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
  CORRECT_NOOP: 'Correctly left alone (feed re-sent the same value)',
  CORRECT_UNCHANGED: 'Correctly unchanged',
  CORRECT_INSERT: 'Correctly inserted',
  TIMESTAMP_OK: 'Last modified is consistent',

  MISSING_UPDATE: 'Update never applied',
  WRONG_VALUE: 'Updated to the wrong value',
  UNEXPECTED_CHANGE: 'Changed with nothing asking for it',
  MISSING_INSERT: 'Record never inserted',
  WRONG_INSERT_VALUE: 'Inserted with the wrong value',
  UNEXPECTED_INSERT: 'Row appeared with nothing asking for it',
  ROW_MISSING_IN_AFTER: 'Row missing from current file',
  TIMESTAMP_NOT_UPDATED: 'Last modified not bumped',
  TIMESTAMP_REGRESSED: 'Last modified went backwards',

  NOOP_TIMESTAMP_MOVED: 'Record re-stamped though nothing changed',
  TIMESTAMP_MOVED_WITHOUT_CHANGE: 'Last modified moved without a data change',
  TIMESTAMP_UNPARSEABLE: 'Last modified is not a readable date',
  DUPLICATE_KEY: 'Duplicate key',

  KEY: 'Key',
  NOT_EVALUATED: 'Not evaluated',
};

export const ROW_TYPE_LABELS: Record<string, string | undefined> = {
  UPDATE_EXPECTED: 'Update expected',
  NOOP_EXPECTED: 'No change needed',
  INSERT_EXPECTED: 'Insert expected',
  UNTOUCHED: 'Not in the feed',
  UNEXPECTED_INSERT: 'Unexpected row',
  DELETED: 'Deleted row',
};
