import { apiRequest } from './api';
import type { ChartStyle } from '../types/dashboard';

/**
 * Client for `POST /charts/style` — restyling a chart already on the canvas.
 *
 * Presentation only: the backend never re-runs the query, so this is fast and
 * cannot change a number. Pass `request` for a natural-language edit ("make the
 * bars orange"), or `style` alone for a direct one from the style panel, which
 * skips the model entirely.
 *
 * `style` is always the widget's *whole* current block, not a diff — the backend
 * merges the patch over it and hands back the merged result to store.
 */
export interface StyleChartResult {
  vega_lite_spec: Record<string, unknown>;
  style: ChartStyle;
  valid: boolean;
  warnings: string[];
}

/** A request the backend could not turn into a style change. */
export interface StyleChartRejected {
  valid: false;
  warnings: string[];
  error?: string;
}

export async function styleChart(
  vegaLiteSpec: Record<string, unknown>,
  style?: ChartStyle,
  request?: string,
): Promise<StyleChartResult> {
  const res = await apiRequest<StyleChartResult | StyleChartRejected>('/charts/style', {
    method: 'POST',
    body: {
      vega_lite_spec: vegaLiteSpec,
      ...(style ? { style } : {}),
      ...(request ? { request } : {}),
    },
  });
  if (!res || res.valid === false || !('vega_lite_spec' in res)) {
    const rejected = res as StyleChartRejected | null;
    const message =
      rejected?.error ||
      rejected?.warnings?.[0] ||
      'Could not update chart style.';
    throw new Error(message);
  }
  return res;
}
