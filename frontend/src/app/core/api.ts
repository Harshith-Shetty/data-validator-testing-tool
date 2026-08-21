import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { FileRole, RunResults, RunSummary, TestConfig, ValidationTest } from './models';

const BASE = '/api';

export interface ResultFilters {
  status?: string;
  row_type?: string;
  search?: string;
  limit?: number;
  offset?: number;
}

@Injectable({ providedIn: 'root' })
export class Api {
  private readonly http = inject(HttpClient);

  listTests(): Observable<ValidationTest[]> {
    return this.http.get<ValidationTest[]>(`${BASE}/tests`);
  }

  getTest(id: string): Observable<ValidationTest> {
    return this.http.get<ValidationTest>(`${BASE}/tests/${id}`);
  }

  createTest(name: string, description = ''): Observable<ValidationTest> {
    return this.http.post<ValidationTest>(`${BASE}/tests`, { name, description });
  }

  deleteTest(id: string): Observable<void> {
    return this.http.delete<void>(`${BASE}/tests/${id}`);
  }

  uploadFile(id: string, role: FileRole, file: File): Observable<ValidationTest> {
    const body = new FormData();
    body.append('file', file, file.name);
    return this.http.post<ValidationTest>(`${BASE}/tests/${id}/files/${role}`, body);
  }

  /** Reads a file straight off the backend's disk — for running frontend and
   * backend on the same machine, so nothing has to be re-uploaded. */
  loadLocalFile(id: string, role: FileRole, path: string): Observable<ValidationTest> {
    return this.http.post<ValidationTest>(`${BASE}/tests/${id}/files/${role}/local`, { path });
  }

  saveConfig(id: string, config: TestConfig): Observable<ValidationTest> {
    return this.http.put<ValidationTest>(`${BASE}/tests/${id}/config`, config);
  }

  /** With no draft, suggests a whole config from scratch. Passed a draft, only
   * fills in the fields left empty on it — e.g. clear `delta_column_map` to
   * re-suggest just the mapping while keeping the rest as-is. */
  suggestConfig(id: string, draft?: TestConfig): Observable<TestConfig> {
    return this.http.post<TestConfig>(`${BASE}/tests/${id}/config/suggest`, draft ?? {});
  }

  runTest(id: string): Observable<RunSummary> {
    return this.http.post<RunSummary>(`${BASE}/tests/${id}/run`, {});
  }

  listRuns(id: string): Observable<RunSummary[]> {
    return this.http.get<RunSummary[]>(`${BASE}/tests/${id}/runs`);
  }

  getRun(id: string, runId: string, filters: ResultFilters = {}): Observable<RunResults> {
    let params = new HttpParams();
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== null && value !== '') {
        params = params.set(key, String(value));
      }
    }
    return this.http.get<RunResults>(`${BASE}/tests/${id}/runs/${runId}`, { params });
  }

  exportUrl(id: string, runId: string, status?: string): string {
    const query = status ? `?status=${encodeURIComponent(status)}` : '';
    return `${BASE}/tests/${id}/runs/${runId}/export${query}`;
  }
}
