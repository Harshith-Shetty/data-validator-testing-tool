import { Component, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { Api } from '../../core/api';
import { ValidationTest } from '../../core/models';

@Component({
  selector: 'app-dashboard',
  imports: [FormsModule, RouterLink, DatePipe],
  templateUrl: './dashboard.html',
  styleUrl: './dashboard.scss',
})
export class Dashboard {
  private readonly api = inject(Api);
  private readonly router = inject(Router);

  readonly tests = signal<ValidationTest[]>([]);
  readonly loading = signal(true);
  readonly error = signal('');
  readonly creating = signal(false);
  readonly showForm = signal(false);

  name = '';
  description = '';

  constructor() {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.api.listTests().subscribe({
      next: (tests) => {
        this.tests.set(tests);
        this.loading.set(false);
      },
      error: (err) => {
        this.error.set(this.message(err));
        this.loading.set(false);
      },
    });
  }

  create(): void {
    if (!this.name.trim() || this.creating()) {
      return;
    }
    this.creating.set(true);
    this.api.createTest(this.name.trim(), this.description.trim()).subscribe({
      next: (test) => {
        this.creating.set(false);
        this.router.navigate(['/tests', test.id]);
      },
      error: (err) => {
        this.error.set(this.message(err));
        this.creating.set(false);
      },
    });
  }

  remove(test: ValidationTest, event: Event): void {
    event.stopPropagation();
    if (!confirm(`Delete "${test.name}" and all of its runs?`)) {
      return;
    }
    this.api.deleteTest(test.id).subscribe({
      next: () => this.tests.update((all) => all.filter((t) => t.id !== test.id)),
      error: (err) => this.error.set(this.message(err)),
    });
  }

  uploadCount(test: ValidationTest): number {
    return Object.keys(test.datasets ?? {}).length;
  }

  statusClass(test: ValidationTest): string {
    const status = test.last_run?.status;
    return status === 'FAIL' ? 'fail' : status === 'WARN' ? 'warn' : status === 'PASS' ? 'pass' : 'info';
  }

  private message(err: unknown): string {
    const detail = (err as { error?: { detail?: string }; message?: string })?.error?.detail;
    return detail ?? (err as { message?: string })?.message ?? 'Something went wrong';
  }
}
