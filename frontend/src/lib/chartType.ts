import type { ChartType, ChartWidget } from '../types/dashboard';

const MARK_TO_TYPE: Record<string, ChartType> = {
  bar: 'bar',
  line: 'line',
  area: 'area',
  point: 'scatter',
  circle: 'scatter',
  arc: 'pie',
  rect: 'heatmap',
  boxplot: 'boxplot',
  box: 'boxplot',
  rule: 'boxplot',
  tick: 'boxplot', // a strip plot is the boxplot family drawn as ticks
};

/**
 * Vega-Lite composite marks. They are siblings of the data mark, never the data
 * mark itself, so reading one would name the wrong family — an error band under
 * a line would make the widget report "boxplot".
 */
const COMPOSITE_MARKS = new Set(['errorband', 'errorbar']);

type SpecNode = {
  mark?: unknown;
  layer?: unknown;
  spec?: unknown;
};

/**
 * The frame a spec actually draws in, and the mark it draws there.
 *
 * Mirrors `charts.primary_layer` on the backend: small multiples put the chart
 * under `spec`, and a sub-type needing a sibling layer (an error band, a jitter
 * overlay, direct labels) means the first layer is not necessarily the data.
 */
function primaryMark(spec: SpecNode | undefined): unknown {
  if (!spec) return undefined;
  const root = (spec.spec && typeof spec.spec === 'object' ? spec.spec : spec) as SpecNode;
  const layers = root.layer;
  if (!Array.isArray(layers)) return root.mark;
  const data = layers.find((layer) => {
    const mark = (layer as SpecNode | null)?.mark;
    const name = typeof mark === 'string'
      ? mark
      : mark && typeof mark === 'object' && 'type' in mark
        ? String((mark as { type: unknown }).type)
        : '';
    return name !== '' && name !== 'text' && !COMPOSITE_MARKS.has(name);
  });
  return (data as SpecNode | undefined)?.mark ?? (layers[0] as SpecNode | undefined)?.mark;
}

/** Best-effort chart type for filtering — stored type, then Vega-Lite mark. */
export function inferChartType(widget: ChartWidget): ChartType | 'other' {
  const stored = widget.chartType?.toLowerCase();
  if (stored) {
    if (stored === 'grouped_bar' || stored === 'grouped-bar') return 'grouped_bar';
    if (stored === 'donut') return 'donut';
    if (stored === 'histogram') return 'histogram';
    if (stored in MARK_TO_TYPE) return MARK_TO_TYPE[stored];
    if (
      stored === 'bar' ||
      stored === 'line' ||
      stored === 'area' ||
      stored === 'scatter' ||
      stored === 'pie' ||
      stored === 'heatmap' ||
      stored === 'boxplot'
    ) {
      return stored;
    }
  }

  const mark = primaryMark(widget.vegaLiteSpec as SpecNode | undefined);
  const markType =
    typeof mark === 'string'
      ? mark
      : mark && typeof mark === 'object' && 'type' in mark
        ? String((mark as { type: unknown }).type)
        : '';

  if (markType === 'arc') {
    // Donut sets innerRadius; treat plain arc as pie.
    const hasInner =
      typeof mark === 'object' &&
      mark !== null &&
      'innerRadius' in mark &&
      (mark as { innerRadius?: unknown }).innerRadius != null;
    return hasInner ? 'donut' : 'pie';
  }

  return MARK_TO_TYPE[markType] ?? 'other';
}

export const FILTERABLE_CHART_TYPES: { id: ChartType; label: string }[] = [
  { id: 'bar', label: 'Bar' },
  { id: 'grouped_bar', label: 'Grouped bar' },
  { id: 'line', label: 'Line' },
  { id: 'area', label: 'Area' },
  { id: 'scatter', label: 'Scatter' },
  { id: 'pie', label: 'Pie' },
  { id: 'donut', label: 'Donut' },
  { id: 'histogram', label: 'Histogram' },
  { id: 'heatmap', label: 'Heatmap' },
  { id: 'boxplot', label: 'Box plot' },
];
