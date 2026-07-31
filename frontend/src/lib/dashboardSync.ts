import { createDashboard, saveChart, updateChart, updateDashboard } from './dashboards';
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
 * Widget `id` and `specVersion` together stand in for the spec. The id covers
 * charts arriving and leaving; the counter covers the two things that rewrite an
 * existing widget's spec in place — a style edit, and a refinement replacing the
 * chart it refined. The spec itself is deliberately not hashed: `data.values`
 * holds every result row, and this runs on every pointer frame of a drag.
 */
export function persistSignature(dashboard: DashboardState): string {
  return JSON.stringify([
    dashboard.dashboardName ?? null,
    dashboard.widgets.map((w) => [
      w.id,
      w.title,
      w.x,
      w.y,
      w.width,
      w.height,
      w.specVersion ?? 0,
    ]),
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
  /** Widget id → the spec version now on the server, for every chart written. */
  syncedSpecVersions: Record<string, number>;
}

/** What a chart row holds beyond the spec. The style block is stored so a
 *  reopened dashboard can keep editing from where the user left off, rather than
 *  showing the styled render with no idea how it got that way. */
function chartSpecOf(widget: ChartWidget): Record<string, unknown> | null {
  return widget.style ? { style: widget.style } : null;
}

/**
 * Get every widget's chart row up to date: create one for a widget that has
 * never been saved, overwrite one whose spec has changed since it was.
 *
 * The version comparison is what stops a drag from re-uploading specs — moving a
 * chart changes the layout signature but not `specVersion`, so nothing here fires.
 */
async function ensureCharts(
  widgets: ChartWidget[],
  datasetId: string | null,
): Promise<Pick<SyncResult, 'newChartIds' | 'syncedSpecVersions'>> {
  const newChartIds: Record<string, string> = {};
  const syncedSpecVersions: Record<string, number> = {};
  // Sequential on purpose: a burst of parallel POSTs from a background save
  // competes with whatever the user is asking the agent for in the foreground,
  // and nothing here is latency-sensitive.
  for (const widget of widgets) {
    const version = widget.specVersion ?? 0;
    if (!widget.backendChartId) {
      const saved = await saveChart({
        name: widget.title,
        vega_lite_spec: widget.vegaLiteSpec,
        dataset_id: datasetId,
        chart_spec: chartSpecOf(widget),
      });
      newChartIds[widget.id] = saved.id;
      syncedSpecVersions[widget.id] = version;
    } else if (version !== (widget.syncedSpecVersion ?? 0)) {
      await updateChart(widget.backendChartId, {
        name: widget.title,
        vega_lite_spec: widget.vegaLiteSpec,
        chart_spec: chartSpecOf(widget),
      });
      syncedSpecVersions[widget.id] = version;
    }
  }
  return { newChartIds, syncedSpecVersions };
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

  const { newChartIds, syncedSpecVersions } = await ensureCharts(dashboard.widgets, datasetId);

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
  return { dashboardId, name, newChartIds, syncedSpecVersions };
}
