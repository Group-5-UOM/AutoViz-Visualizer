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
};

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

  const mark = widget.vegaLiteSpec?.mark;
  const markType =
    typeof mark === 'string'
      ? mark
      : mark && typeof mark === 'object' && 'type' in mark
        ? String((mark as { type: unknown }).type)
        : '';

  if (markType === 'arc') {
    const inner = (widget.vegaLiteSpec as { encoding?: { theta?: unknown } })?.encoding;
    // Donut often sets innerRadius; treat plain arc as pie.
    const hasInner =
      typeof mark === 'object' &&
      mark !== null &&
      'innerRadius' in mark &&
      (mark as { innerRadius?: unknown }).innerRadius != null;
    void inner;
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
