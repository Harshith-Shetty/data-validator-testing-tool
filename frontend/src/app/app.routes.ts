import { Routes } from '@angular/router';

export const routes: Routes = [
  {
    path: '',
    pathMatch: 'full',
    loadComponent: () => import('./pages/dashboard/dashboard').then((m) => m.Dashboard),
    title: 'Data capture validation',
  },
  {
    path: 'tests/:testId',
    loadComponent: () => import('./pages/test-detail/test-detail').then((m) => m.TestDetail),
    title: 'Test setup',
  },
  {
    path: 'tests/:testId/results/:runId',
    loadComponent: () => import('./pages/results/results').then((m) => m.Results),
    title: 'Validation results',
  },
  { path: '**', redirectTo: '' },
];
