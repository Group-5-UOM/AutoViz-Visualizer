import { apiRequest } from './api';

export interface SavedChartResult {
  id: string;
  name: string;
  dataset_id: string | null;
  vega_lite_spec: Record<string, unknown>;
  chart_spec: Record<string, unknown> | null;
  provenance: Record<string, unknown> | null;
  created_at: string;
}

export interface SaveChartPayload {
  name: string;
  vega_lite_spec: Record<string, unknown>;
  dataset_id?: string | null;
  chart_spec?: Record<string, unknown> | null;
  provenance?: Record<string, unknown> | null;
}

export async function saveChart(payload: SaveChartPayload): Promise<SavedChartResult> {
  return apiRequest<SavedChartResult>('/charts/save', {
    method: 'POST',
    body: payload,
  });
}

export interface WidgetSpec {
  chart_id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  order: number;
}

export interface DashboardResult {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  widgets: {
    id: string;
    chart_id: string;
    x: number;
    y: number;
    w: number;
    h: number;
    order: number;
  }[];
}

export async function createDashboard(name: string): Promise<DashboardResult> {
  return apiRequest<DashboardResult>('/dashboards', {
    method: 'POST',
    body: { name },
  });
}

export async function updateDashboard(
  dashboardId: string,
  name?: string,
  widgets?: WidgetSpec[]
): Promise<DashboardResult> {
  return apiRequest<DashboardResult>(`/dashboards/${dashboardId}`, {
    method: 'PUT',
    body: { name, widgets },
  });
}

export async function getChart(chartId: string): Promise<SavedChartResult> {
  return apiRequest<SavedChartResult>(`/charts/${chartId}`, { method: 'GET' });
}

export async function listDashboards(): Promise<{ dashboards: DashboardResult[] }> {
  return apiRequest<{ dashboards: DashboardResult[] }>('/dashboards', { method: 'GET' });
}

export async function getDashboard(dashboardId: string): Promise<DashboardResult> {
  return apiRequest<DashboardResult>(`/dashboards/${dashboardId}`, { method: 'GET' });
}
