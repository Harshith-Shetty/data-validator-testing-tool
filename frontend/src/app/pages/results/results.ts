import { Component, computed, inject, input, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { AgGridAngular } from 'ag-grid-angular';
import type {
  CellClassParams,
  ColDef,
  GridOptions,
  ITooltipParams,
  RowClassParams,
  ValueGetterParams,
} from 'ag-grid-community';
import { themeQuartz } from 'ag-grid-community';

import { Api } from '../../core/api';
import { CellResult, RULE_LABELS, ROW_TYPE_LABELS, RunResults, RunRow } from '../../core/models';

const STATUS_FILTERS = ['ALL', 'FAIL', 'WARN', 'PASS'] as const;
type StatusFilter = (typeof STATUS_FILTERS)[number];

@Component({
  selector: 'app-results',
  imports: [AgGridAngular, FormsModule, RouterLink, DatePipe],
  templateUrl: './results.html',
  styleUrl: './results.scss',
})
export class Results {
  private readonly api = inject(Api);

  readonly testId = input.required<string>();
  readonly runId = input.required<string>();

  readonly results = signal<RunResults | null>(null);
  readonly loading = signal(true);
  readonly error = signal('');
  readonly statusFilter = signal<StatusFilter>('ALL');
  readonly rowTypeFilter = signal('');
  readonly search = signal('');
  readonly showBefore = signal(true);
  readonly selected = signal<RunRow | null>(null);

  readonly statuses = STATUS_FILTERS;
  readonly rowTypeLabels = ROW_TYPE_LABELS;
  readonly ruleLabels = RULE_LABELS;
  readonly theme = themeQuartz.withParams({
    accentColor: '#4f46e5',
    borderColor: '#e2e8f0',
    headerBackgroundColor: '#f8fafc',
    headerTextColor: '#475569',
    fontSize: 13,
    rowHeight: 38,
  });

  readonly summary = computed(() => this.results()?.summary ?? null);

  readonly issueList = computed(() => {
    const issues = this.summary()?.issues_by_code ?? {};
    return Object.entries(issues)
      .map(([code, count]) => ({ code, count, label: RULE_LABELS[code] ?? code }))
      .sort((a, b) => b.count - a.count);
  });

  readonly rowTypeList = computed(() => {
    const types = this.summary()?.rows_by_type ?? {};
    return Object.entries(types).map(([type, count]) => ({
      type,
      count,
      label: ROW_TYPE_LABELS[type] ?? type,
    }));
  });

  readonly gridOptions: GridOptions<RunRow> = {
    animateRows: false,
    suppressCellFocus: false,
    tooltipShowDelay: 200,
    rowClassRules: {
      'dvt-row-fail': (params: RowClassParams<RunRow>) => params.data?.rowStatus === 'FAIL',
    },
    defaultColDef: {
      resizable: true,
      sortable: true,
      filter: true,
      minWidth: 120,
    },
  };

  readonly columnDefs = computed<ColDef<RunRow>[]>(() => {
    const results = this.results();
    if (!results) return [];

    const keyColumns = new Set(results.summary.key_columns);
    const showBefore = this.showBefore();

    const statusColumn: ColDef<RunRow> = {
      headerName: 'Result',
      field: 'rowStatus',
      pinned: 'left',
      width: 110,
      cellRenderer: (params: { value: string }) =>
        `<span class="dvt-status pill ${params.value?.toLowerCase()}">${params.value}</span>`,
    };

    const typeColumn: ColDef<RunRow> = {
      headerName: 'Row',
      field: 'rowType',
      pinned: 'left',
      width: 165,
      valueFormatter: (params) => ROW_TYPE_LABELS[params.value] ?? params.value,
    };

    const timestampColumn = results.summary.last_modified_column;

    const dataColumns = results.columns.map<ColDef<RunRow>>((column) => ({
      headerName: column,
      colId: column,
      pinned: keyColumns.has(column) ? 'left' : undefined,
      // "before → current" needs room, and timestamps are the widest values of all.
      width: keyColumns.has(column) ? 120 : column === timestampColumn ? 340 : 210,
      valueGetter: (params: ValueGetterParams<RunRow>) =>
        params.data?.cells?.[column]?.after ?? '',
      cellRenderer: (params: { data?: RunRow }) =>
        this.renderCell(params.data?.cells?.[column], showBefore),
      tooltipValueGetter: (params: ITooltipParams<RunRow>) =>
        this.tooltip(params.data?.cells?.[column]),
      cellClassRules: {
        'dvt-cell-pass': (p: CellClassParams<RunRow>) =>
          p.data?.cells?.[column]?.status === 'PASS',
        'dvt-cell-fail': (p: CellClassParams<RunRow>) =>
          p.data?.cells?.[column]?.status === 'FAIL',
        'dvt-cell-warn': (p: CellClassParams<RunRow>) =>
          p.data?.cells?.[column]?.status === 'WARN',
        'dvt-cell-info': (p: CellClassParams<RunRow>) =>
          p.data?.cells?.[column]?.status === 'INFO',
      },
    }));

    const issueColumn: ColDef<RunRow> = {
      headerName: 'Issues',
      colId: '__issues',
      flex: 1,
      minWidth: 260,
      sortable: false,
      valueGetter: (params: ValueGetterParams<RunRow>) =>
        (params.data?.messages ?? []).join(' · '),
      tooltipValueGetter: (params: ITooltipParams<RunRow>) =>
        (params.data?.messages ?? []).join('\n'),
    };

    return [statusColumn, typeColumn, ...dataColumns, issueColumn];
  });

  constructor() {
    queueMicrotask(() => this.load());
  }

  load(): void {
    this.loading.set(true);
    this.api
      .getRun(this.testId(), this.runId(), {
        status: this.statusFilter() === 'ALL' ? undefined : this.statusFilter(),
        row_type: this.rowTypeFilter() || undefined,
        search: this.search() || undefined,
        limit: 5000,
      })
      .subscribe({
        next: (results) => {
          this.results.set(results);
          this.loading.set(false);
        },
        error: (err) => {
          this.error.set(this.message(err));
          this.loading.set(false);
        },
      });
  }

  setStatus(status: StatusFilter): void {
    this.statusFilter.set(status);
    this.load();
  }

  setRowType(type: string): void {
    this.rowTypeFilter.set(this.rowTypeFilter() === type ? '' : type);
    this.load();
  }

  applySearch(): void {
    this.load();
  }

  toggleBefore(): void {
    this.showBefore.set(!this.showBefore());
  }

  onRowClicked(event: { data?: RunRow }): void {
    this.selected.set(event.data ?? null);
  }

  exportUrl(): string {
    const status = this.statusFilter();
    return this.api.exportUrl(this.testId(), this.runId(), status === 'ALL' ? undefined : status);
  }

  passRate(): number {
    const summary = this.summary();
    if (!summary?.cells_total) return 0;
    return Math.round((summary.cells_passed / summary.cells_total) * 100);
  }

  statusClass(status: string | undefined): string {
    return (status ?? 'info').toLowerCase();
  }

  private renderCell(cell: CellResult | undefined, showBefore: boolean): string {
    if (!cell) return '';
    const after = this.escape(cell.after) || '<span class="muted">—</span>';
    if (!cell.changed || !showBefore) {
      return `<span class="dvt-value">${after}</span>`;
    }
    const before = this.escape(this.beforeDisplay(cell)) || '∅';
    return `<span class="dvt-value"><span class="dvt-before">${before}</span><span class="dvt-arrow">→</span>${after}</span>`;
  }

  /** An unchanged cell doesn't carry `before` over the wire — it equals
   * `after` — so this is where that fallback happens for display purposes. */
  beforeDisplay(cell: CellResult): string {
    return (cell.changed ? cell.before : cell.after) ?? '';
  }

  private tooltip(cell: CellResult | undefined): string {
    if (!cell) return '';
    const parts = [`${cell.column}: ${RULE_LABELS[cell.code] ?? cell.code}`];
    parts.push(`before: ${this.beforeDisplay(cell) || '∅'}`);
    parts.push(`current: ${cell.after || '∅'}`);
    if (cell.expected !== null && cell.expected !== undefined) {
      parts.push(`delta says: ${cell.expected}`);
    }
    if (cell.message) parts.push(cell.message);
    return parts.join('\n');
  }

  private escape(value: string | null | undefined): string {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  private message(err: unknown): string {
    const detail = (err as { error?: { detail?: string }; message?: string })?.error?.detail;
    return detail ?? (err as { message?: string })?.message ?? 'Something went wrong';
  }
}
