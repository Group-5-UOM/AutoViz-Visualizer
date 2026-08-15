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
  is_public: boolean;
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
  widgets?: WidgetSpec[],
  is_public?: boolean
): Promise<DashboardResult> {
  return apiRequest<DashboardResult>(`/dashboards/${dashboardId}`, {
    method: 'PUT',
    body: { name, widgets, is_public },
  });
}

export async function getChart(chartId: string): Promise<SavedChartResult> {
  return apiRequest<SavedChartResult>(`/charts/${chartId}`, { method: 'GET' });
}

/**
 * Overwrite a chart that has already been saved. Only the fields passed are
 * written, so an edit that changed the spec leaves the name as it was.
 */
export async function updateChart(
  chartId: string,
  fields: Partial<Pick<SaveChartPayload, 'name' | 'vega_lite_spec' | 'chart_spec'>>
): Promise<SavedChartResult> {
  return apiRequest<SavedChartResult>(`/charts/${chartId}`, {
    method: 'PUT',
    body: fields,
  });
}

export async function listDashboards(): Promise<{ dashboards: DashboardResult[] }> {
  return apiRequest<{ dashboards: DashboardResult[] }>('/dashboards', { method: 'GET' });
}

export async function getDashboard(dashboardId: string): Promise<DashboardResult> {
  return apiRequest<DashboardResult>(`/dashboards/${dashboardId}`, { method: 'GET' });
}

export async function deleteDashboard(dashboardId: string): Promise<{ removed: boolean; id: string }> {
  return apiRequest<{ removed: boolean; id: string }>(`/dashboards/${dashboardId}`, { method: 'DELETE' });
}

export interface SharedDashboardResult extends DashboardResult {
  charts: Record<string, { id: string; name: string; dataset_id: string | null; spec: Record<string, unknown> }>;
}

export async function getSharedDashboard(dashboardId: string): Promise<SharedDashboardResult> {
  return apiRequest<SharedDashboardResult>(`/dashboards/shared/${dashboardId}`, { method: 'GET', auth: false });
}
