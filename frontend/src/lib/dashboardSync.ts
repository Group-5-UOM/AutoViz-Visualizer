import { createDashboard, saveChart, updateDashboard } from './dashboards';
import type { ChartWidget, DashboardState } from '../types/dashboard';

/**
 * Pushing the canvas to the server, and deciding when it needs pushing.
 *
 * Kept free of React so the ordering rules below are readable on their own —
 * the hook in `useDashboard` supplies the timer and the status, nothing else.
 */

/**
 * A string that changes exactly when something worth persisting changes.
 *
 * Compared against the last-saved value, this is what makes "unsaved" precise:
 * loading a dashboard does not immediately save it back, and a chart dragged in
 * a circle and returned to its origin costs no request. `backendChartId` is
 * deliberately absent — it is an outcome of saving, not a reason to save.
 *
 * Widget `id` stands in for the spec: `widgetsFromAgent` mints a fresh id per
 * chart and never rewrites an existing one's spec, so equal ids mean equal
 * specs.
 */
export function persistSignature(dashboard: DashboardState): string {
  return JSON.stringify([
    dashboard.dashboardName ?? null,
    dashboard.widgets.map((w) => [w.id, w.title, w.x, w.y, w.width, w.height]),
  ]);
}

/**
 * What to call a dashboard nobody has named. Derived from the CSV rather than
 * left as a placeholder, so a list of auto-saved boards is still readable:
 * `titanic_clean.csv` becomes "Titanic clean".
 */
export function defaultDashboardName(fileName: string | null | undefined): string {
  const stem = (fileName ?? '')
    .replace(/\.[^./\\]+$/, '')
    .replace(/[_-]+/g, ' ')
    .trim();
  if (!stem) return 'Untitled dashboard';
  return stem.charAt(0).toUpperCase() + stem.slice(1);
}

export interface SyncResult {
  dashboardId: string;
  name: string;
  /** Widget id → the chart row just created for it. Empty on a layout-only save. */
  newChartIds: Record<string, string>;
}

/** Chart ids the layout will reference, minted for any widget still unsaved. */
async function ensureCharts(
  widgets: ChartWidget[],
  datasetId: string | null,
): Promise<Record<string, string>> {
  const created: Record<string, string> = {};
  // Sequential on purpose: a burst of parallel POSTs from a background save
  // competes with whatever the user is asking the agent for in the foreground,
  // and nothing here is latency-sensitive.
  for (const widget of widgets) {
    if (widget.backendChartId) continue;
    const saved = await saveChart({
      name: widget.title,
      vega_lite_spec: widget.vegaLiteSpec,
      dataset_id: datasetId,
    });
    created[widget.id] = saved.id;
  }
  return created;
}

/**
 * Persist the whole canvas: create the dashboard if it is new, save any chart
 * that has never been saved, then write the layout.
 *
 * Returns what the caller has to fold back into state rather than mutating it,
 * so the snapshot passed in can stay the immutable React value it came from.
 */
export async function syncDashboard(
  dashboard: DashboardState,
  datasetId: string | null,
  defaultName: string,
): Promise<SyncResult> {
  let dashboardId = dashboard.dashboardId;
  let name = dashboard.dashboardName ?? defaultName;

  if (!dashboardId) {
    const created = await createDashboard(name);
    dashboardId = created.id;
    name = created.name;
  }

  const newChartIds = await ensureCharts(dashboard.widgets, datasetId);

  const widgets = dashboard.widgets.map((widget, i) => ({
    chart_id: widget.backendChartId ?? newChartIds[widget.id],
    // Drag deltas are integers today, but the columns are INTEGER and the
    // request body is typed `int` — rounding here beats a 422 mid-drag.
    x: Math.round(widget.x),
    y: Math.round(widget.y),
    w: Math.round(widget.width),
    h: Math.round(widget.height),
    order: i,
  }));

  await updateDashboard(dashboardId, name, widgets);
  return { dashboardId, name, newChartIds };
}
