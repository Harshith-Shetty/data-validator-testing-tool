import { Component, computed, inject, input, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { Api } from '../../core/api';
import {
  DELTA_MODE_LABELS,
  DatasetSummary,
  DeltaValueMode,
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
  imports: [FormsModule, RouterLink, DatePipe],
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

  readonly deltaModes: DeltaValueMode[] = ['new_value', 'old_value', 'presence_only'];
  readonly modeLabels = DELTA_MODE_LABELS;

  readonly dataColumns = computed(() => {
    const test = this.test();
    return test?.datasets?.before?.columns ?? test?.datasets?.after?.columns ?? [];
  });

  readonly deltaColumns = computed(() => this.test()?.datasets?.delta?.columns ?? []);

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

  keyColumn(): string {
    return this.config()?.key_columns[0] ?? '';
  }

  deltaKeyColumn(): string {
    return this.config()?.delta_key_columns[0] ?? '';
  }

  setKeyColumn(column: string): void {
    const config = this.config();
    if (config) config.key_columns = [column];
  }

  setDeltaKeyColumn(column: string): void {
    const config = this.config();
    if (config) config.delta_key_columns = [column];
  }

  setLastModified(column: string): void {
    const config = this.config();
    if (config) config.last_modified_column = column || null;
  }

  payloadDeltaColumns(): string[] {
    const keys = new Set(this.config()?.delta_key_columns ?? []);
    return this.deltaColumns().filter((c) => !keys.has(c));
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
