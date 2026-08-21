import { Component, computed, inject, input, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { ColumnPicker } from '../../shared/column-picker';

import { Api } from '../../core/api';
import {
  DatasetSummary,
  FileRole,
  RunSummary,
  TestConfig,
  ValidationTest,
} from '../../core/models';

interface UploadSlot {
  role: FileRole;
  title: string;
  blurb: string;
}

@Component({
  selector: 'app-test-detail',
  imports: [FormsModule, RouterLink, DatePipe, ColumnPicker],
  templateUrl: './test-detail.html',
  styleUrl: './test-detail.scss',
})
export class TestDetail {
  private readonly api = inject(Api);
  private readonly router = inject(Router);

  readonly testId = input.required<string>();

  readonly test = signal<ValidationTest | null>(null);
  readonly runs = signal<RunSummary[]>([]);
  readonly error = signal('');
  readonly notice = signal('');
  readonly busyRole = signal<FileRole | null>(null);
  readonly running = signal(false);
  readonly saving = signal(false);
  readonly dragRole = signal<FileRole | null>(null);
  readonly columnFilter = signal('');
  readonly mappingFilter = signal('');
  readonly localPaths = signal<Partial<Record<FileRole, string>>>({});

  readonly slots: UploadSlot[] = [
    {
      role: 'before',
      title: '1 · Before data',
      blurb: 'The snapshot as it looked before the capture run.',
    },
    {
      role: 'after',
      title: '2 · Current data',
      blurb: 'The snapshot as it looks now, after the capture run.',
    },
    {
      role: 'delta',
      title: '3 · Delta file',
      blurb: 'The changes the capture run was supposed to apply.',
    },
  ];


  readonly dataColumns = computed(() => {
    const test = this.test();
    return test?.datasets?.before?.columns ?? test?.datasets?.after?.columns ?? [];
  });

  readonly deltaColumns = computed(() => this.test()?.datasets?.delta?.columns ?? []);

  /** Data columns available to compare, minus the key and last-modified picks. */
  readonly comparableColumns = computed(() => {
    const config = this.config();
    const keys = new Set(config?.key_columns ?? []);
    return this.dataColumns().filter(
      (column) => !keys.has(column) && column !== config?.last_modified_column,
    );
  });

  readonly visibleComparableColumns = computed(() => {
    const needle = this.columnFilter().trim().toLowerCase();
    if (!needle) return this.comparableColumns();
    return this.comparableColumns().filter((column) => column.toLowerCase().includes(needle));
  });

  readonly ready = computed(() => {
    const datasets = this.test()?.datasets ?? {};
    return !!datasets.before && !!datasets.after && !!datasets.delta;
  });

  constructor() {
    queueMicrotask(() => this.load());
  }

  load(): void {
    this.api.getTest(this.testId()).subscribe({
      next: (test) => this.test.set(test),
      error: (err) => this.error.set(this.message(err)),
    });
    this.api.listRuns(this.testId()).subscribe({
      next: (runs) => this.runs.set(runs),
      error: () => undefined,
    });
  }

  dataset(role: FileRole): DatasetSummary | undefined {
    return this.test()?.datasets?.[role];
  }

  config(): TestConfig | null {
    return this.test()?.config ?? null;
  }

  // ------------------------------------------------------------------ uploads

  onFileInput(role: FileRole, event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (file) {
      this.upload(role, file);
    }
    input.value = '';
  }

  onDrop(role: FileRole, event: DragEvent): void {
    event.preventDefault();
    this.dragRole.set(null);
    const file = event.dataTransfer?.files?.[0];
    if (file) {
      this.upload(role, file);
    }
  }

  onDragOver(role: FileRole, event: DragEvent): void {
    event.preventDefault();
    this.dragRole.set(role);
  }

  upload(role: FileRole, file: File): void {
    this.error.set('');
    this.busyRole.set(role);
    this.api.uploadFile(this.testId(), role, file).subscribe({
      next: (test) => {
        this.test.set(test);
        this.busyRole.set(null);
        this.notice.set(`${file.name} loaded — ${test.datasets[role]?.row_count ?? 0} rows.`);
      },
      error: (err) => {
        this.error.set(this.message(err));
        this.busyRole.set(null);
      },
    });
  }

  localPathFor(role: FileRole): string {
    return this.localPaths()[role] ?? '';
  }

  setLocalPath(role: FileRole, path: string): void {
    this.localPaths.update((paths) => ({ ...paths, [role]: path }));
  }

  /** Reads a file straight off the backend's disk — handy when frontend and
   * backend are running on the same machine, so nothing has to be uploaded. */
  loadFromPath(role: FileRole): void {
    const path = this.localPathFor(role).trim();
    if (!path || this.busyRole()) return;
    this.error.set('');
    this.busyRole.set(role);
    this.api.loadLocalFile(this.testId(), role, path).subscribe({
      next: (test) => {
        this.test.set(test);
        this.busyRole.set(null);
        this.notice.set(`${path} loaded — ${test.datasets[role]?.row_count ?? 0} rows.`);
      },
      error: (err) => {
        this.error.set(this.message(err));
        this.busyRole.set(null);
      },
    });
  }

  // ------------------------------------------------------------------- config

  toggleCompareColumn(column: string, checked: boolean): void {
    const config = this.config();
    if (!config) return;
    const set = new Set(config.compare_columns);
    checked ? set.add(column) : set.delete(column);
    config.compare_columns = this.dataColumns().filter((c) => set.has(c));
  }

  isCompared(column: string): boolean {
    return this.config()?.compare_columns.includes(column) ?? false;
  }

  mappingFor(deltaColumn: string): string {
    const mapping = this.config()?.delta_column_map.find((m) => m.delta_column === deltaColumn);
    return mapping?.target_column ?? '';
  }

  setMapping(deltaColumn: string, targetColumn: string): void {
    const config = this.config();
    if (!config) return;
    const rest = config.delta_column_map.filter((m) => m.delta_column !== deltaColumn);
    config.delta_column_map = targetColumn
      ? [...rest, { delta_column: deltaColumn, target_column: targetColumn }]
      : rest;
  }

  /** Row matching is one or more column pairs, ANDed together. */
  keyPairs(): { index: number; data: string; delta: string }[] {
    const config = this.config();
    if (!config) return [];
    const count = Math.max(config.key_columns.length, config.delta_key_columns.length, 1);
    return Array.from({ length: count }, (_, index) => ({
      index,
      data: config.key_columns[index] ?? '',
      delta: config.delta_key_columns[index] ?? '',
    }));
  }

  canRemoveKeyColumn(): boolean {
    return this.keyPairs().length > 1;
  }

  setKeyColumnAt(index: number, column: string): void {
    const config = this.config();
    if (!config) return;
    const columns = [...config.key_columns];
    columns[index] = column;
    config.key_columns = columns;
  }

  setDeltaKeyColumnAt(index: number, column: string): void {
    const config = this.config();
    if (!config) return;
    const columns = [...config.delta_key_columns];
    columns[index] = column;
    config.delta_key_columns = columns;
  }

  addKeyColumn(): void {
    const config = this.config();
    if (!config) return;
    config.key_columns = [...config.key_columns, ''];
    config.delta_key_columns = [...config.delta_key_columns, ''];
  }

  removeKeyColumnAt(index: number): void {
    const config = this.config();
    if (!config || config.key_columns.length <= 1) return;
    config.key_columns = config.key_columns.filter((_, i) => i !== index);
    config.delta_key_columns = config.delta_key_columns.filter((_, i) => i !== index);
  }

  setLastModified(column: string): void {
    const config = this.config();
    if (config) config.last_modified_column = column || null;
  }

  payloadDeltaColumns(): string[] {
    const keys = new Set(this.config()?.delta_key_columns ?? []);
    return this.deltaColumns().filter((c) => !keys.has(c));
  }

  /** Mapping rows matching the search box, by delta column or by what it sets. */
  visibleMappingColumns(): string[] {
    const needle = this.mappingFilter().trim().toLowerCase();
    const all = this.payloadDeltaColumns();
    if (!needle) return all;
    return all.filter(
      (column) =>
        column.toLowerCase().includes(needle) ||
        this.mappingFor(column).toLowerCase().includes(needle),
    );
  }

  mappedCount(): number {
    return this.payloadDeltaColumns().filter((c) => !!this.mappingFor(c)).length;
  }

  resetMapping(): void {
    const test = this.test();
    const config = this.config();
    if (!test || !config || !config.delta_column_map.length) return;
    this.test.set({ ...test, config: { ...config, delta_column_map: [] } });
    this.notice.set('Delta column mapping cleared.');
  }

  /** Re-suggests just the delta → data mapping, leaving the rest of the
   * config (row matching, compare columns, rules) exactly as it is. */
  autoPopulateMapping(): void {
    const test = this.test();
    const config = this.config();
    if (!test || !config) return;
    this.error.set('');
    const draft: TestConfig = { ...config, delta_column_map: [] };
    this.api.suggestConfig(this.testId(), draft).subscribe({
      next: (suggested) => {
        const current = this.test();
        if (!current) return;
        this.test.set({
          ...current,
          config: { ...current.config, delta_column_map: suggested.delta_column_map },
        });
        const mapped = suggested.delta_column_map.length;
        this.notice.set(
          mapped
            ? `Mapped ${mapped} delta column${mapped === 1 ? '' : 's'} automatically.`
            : 'No confident column matches were found.',
        );
      },
      error: (err) => this.error.set(this.message(err)),
    });
  }

  saveConfig(): void {
    const config = this.config();
    if (!config) return;
    this.saving.set(true);
    this.api.saveConfig(this.testId(), config).subscribe({
      next: (test) => {
        this.test.set(test);
        this.saving.set(false);
        this.notice.set('Configuration saved.');
      },
      error: (err) => {
        this.error.set(this.message(err));
        this.saving.set(false);
      },
    });
  }

  reSuggest(): void {
    this.api.suggestConfig(this.testId()).subscribe({
      next: (config) => {
        const test = this.test();
        if (test) {
          this.test.set({ ...test, config });
          this.notice.set('Columns re-detected from the uploaded files.');
        }
      },
      error: (err) => this.error.set(this.message(err)),
    });
  }

  // ---------------------------------------------------------------------- run

  run(): void {
    const config = this.config();
    if (!config || this.running()) return;
    this.error.set('');
    this.running.set(true);
    this.api.saveConfig(this.testId(), config).subscribe({
      next: () =>
        this.api.runTest(this.testId()).subscribe({
          next: (summary) => {
            this.running.set(false);
            this.router.navigate(['/tests', this.testId(), 'results', summary.run_id]);
          },
          error: (err) => {
            this.error.set(this.message(err));
            this.running.set(false);
          },
        }),
      error: (err) => {
        this.error.set(this.message(err));
        this.running.set(false);
      },
    });
  }

  statusClass(status: string): string {
    return status === 'FAIL' ? 'fail' : status === 'WARN' ? 'warn' : 'pass';
  }

  previewColumns(role: FileRole): string[] {
    return this.dataset(role)?.columns ?? [];
  }

  previewValue(row: Record<string, unknown>, column: string): string {
    const value = row[column];
    return value === null || value === undefined ? '' : String(value);
  }

  private message(err: unknown): string {
    const detail = (err as { error?: { detail?: string }; message?: string })?.error?.detail;
    return detail ?? (err as { message?: string })?.message ?? 'Something went wrong';
  }
}
