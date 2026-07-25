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
