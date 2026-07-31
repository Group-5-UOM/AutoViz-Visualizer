/**
 * Reading the result rows back out of a generated Vega-Lite spec.
 *
 * The backend inlines the result table as `data.values`, so the table view
 * needs no separate fetch and no extra field on ChartWidget — the rows the
 * chart drew are already in hand.
 */

/** Rows a generated spec carries inline, or null if it has none. */
export function specRows(
  spec: Record<string, unknown> | undefined,
): Record<string, unknown>[] | null {
  const data = spec?.data as { values?: unknown } | undefined;
  const values = data?.values;
  if (!Array.isArray(values) || values.length === 0) return null;
  if (typeof values[0] !== 'object' || values[0] === null) return null;
  return values as Record<string, unknown>[];
}

/** Rows past this are not rendered; 5k rows of DOM janks the whole canvas. */
export const MAX_TABLE_ROWS = 500;

/** The data layer of a generated spec — direct labels make it layered. Mirrors
 *  backend `services/charts.primary_layer`. */
function primaryLayer(spec: Record<string, unknown> | undefined): Record<string, unknown> {
  const layers = spec?.layer;
  return (Array.isArray(layers) ? layers[0] : spec) ?? {};
}

/**
 * The series a chart draws, in the order Vega-Lite assigned them colours — so a
 * colour picker can list them alongside the swatch each one currently has.
 *
 * Empty when the chart has no colour scale (a single-series bar chart), or when
 * colour carries a measure rather than categories (a heatmap): neither has
 * series to name, and both are recoloured as a whole instead.
 */
export function specSeries(spec: Record<string, unknown> | undefined): string[] {
  const encoding = primaryLayer(spec).encoding as Record<string, unknown> | undefined;
  const color = encoding?.color as { field?: string; type?: string } | undefined;
  if (!color?.field || color.type === 'quantitative') return [];

  const rows = specRows(spec);
  if (!rows) return [];
  const seen: string[] = [];
  for (const row of rows) {
    const value = row[color.field];
    if (value === undefined || value === null) continue;
    const key = String(value);
    if (!seen.includes(key)) seen.push(key);
  }
  return seen;
}

/** Name of the interval selection the backend attaches to brushable charts. */
export const BRUSH_SIGNAL = 'autoviz_brush';

/**
 * A brush extent as Vega reports it: `{field: [lo, hi]}` per brushed axis, and
 * `{}` once the selection is cleared.
 */
export type BrushExtent = Record<string, [number, number]>;

export function hasBrush(extent: BrushExtent | null): extent is BrushExtent {
  return !!extent && Object.keys(extent).length > 0;
}

/**
 * Rows falling inside the brush, on every brushed axis at once.
 *
 * The extent's keys are the encoded field names, so they index rows directly.
 * Rows whose value on a brushed field is missing or non-numeric are excluded —
 * they are not inside the selection in any meaningful sense.
 */
export function rowsInBrush(
  rows: Record<string, unknown>[],
  extent: BrushExtent | null,
): Record<string, unknown>[] {
  if (!hasBrush(extent)) return rows;
  const bounds = Object.entries(extent);
  return rows.filter((row) =>
    bounds.every(([field, range]) => {
      const value = row[field];
      const n = value instanceof Date ? value.getTime() : value;
      if (typeof n !== 'number' || !Number.isFinite(n)) return false;
      const [lo, hi] = range[0] <= range[1] ? range : [range[1], range[0]];
      return n >= lo && n <= hi;
    }),
  );
}
