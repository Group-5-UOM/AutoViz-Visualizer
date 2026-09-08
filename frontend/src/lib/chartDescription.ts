/**
 * Build a short plain-English paragraph describing what a chart shows.
 *
 * Uses the user request (task), chart type, and analysis_plan fields — no LLM
 * call. Kept free of React so it can be unit-tested and reused when a plan is
 * re-run from the editor.
 */

const CHART_LABELS: Record<string, string> = {
  bar: 'bar chart',
  grouped_bar: 'grouped bar chart',
  line: 'line chart',
  area: 'area chart',
  pie: 'pie chart',
  donut: 'donut chart',
  scatter: 'scatter plot',
  histogram: 'histogram',
  heatmap: 'heatmap',
  boxplot: 'box plot',
};

function cleanTask(task: string): string {
  return task.replace(/\s*\[Resolved constraints:[^\]]*\]\s*$/i, '').trim();
}

function humanCol(name: string): string {
  return name.replace(/_/g, ' ').trim();
}

function listCols(cols: string[]): string {
  if (cols.length === 0) return '';
  if (cols.length === 1) return humanCol(cols[0]);
  if (cols.length === 2) return `${humanCol(cols[0])} and ${humanCol(cols[1])}`;
  return `${cols.slice(0, -1).map(humanCol).join(', ')}, and ${humanCol(cols[cols.length - 1])}`;
}

function chartKind(type: string | undefined): string {
  if (!type) return 'chart';
  return CHART_LABELS[type] ?? `${type.replace(/_/g, ' ')} chart`;
}

export function describeChart(input: {
  task?: string | null;
  chartType?: string | null;
  plan?: Record<string, unknown> | null;
  rowCount?: number | null;
}): string {
  const task = cleanTask(input.task || '');
  const plan = input.plan && typeof input.plan === 'object' ? input.plan : null;
  const type =
    input.chartType ||
    (typeof (plan?.chart as { type?: string } | undefined)?.type === 'string'
      ? (plan!.chart as { type: string }).type
      : undefined);

  const sentences: string[] = [];

  if (task) {
    sentences.push(`This ${chartKind(type)} answers: “${task.charAt(0).toUpperCase()}${task.slice(1)}”.`);
  } else {
    sentences.push(`This is a ${chartKind(type)} built from your dataset.`);
  }

  if (plan) {
    const chart = (plan.chart || {}) as {
      x?: string;
      y?: string;
      color?: string;
    };
    const groupBy = Array.isArray(plan.group_by)
      ? plan.group_by.filter((c): c is string => typeof c === 'string')
      : [];
    const aggs = Array.isArray(plan.aggregations) ? plan.aggregations : [];
    const filters = Array.isArray(plan.filters) ? plan.filters : [];

    const how: string[] = [];
    if (groupBy.length) {
      how.push(`grouped by ${listCols(groupBy)}`);
    }
    if (aggs.length) {
      const bits = aggs
        .map((a) => {
          if (!a || typeof a !== 'object') return null;
          const row = a as { fn?: string; column?: string };
          if (!row.fn) return null;
          if (row.fn === 'count') return 'a count of rows';
          if (row.column) return `the ${row.fn} of ${humanCol(row.column)}`;
          return `a ${row.fn}`;
        })
        .filter((s): s is string => Boolean(s));
      if (bits.length) how.push(`measuring ${bits.join(' and ')}`);
    }
    if (chart.x || chart.y) {
      const axes: string[] = [];
      if (chart.x) axes.push(`${humanCol(chart.x)} on the horizontal axis`);
      if (chart.y) axes.push(`${humanCol(chart.y)} on the vertical axis`);
      if (axes.length) how.push(axes.join(' and '));
    }
    if (chart.color) {
      how.push(`coloured by ${humanCol(chart.color)}`);
    }
    if (filters.length) {
      how.push(`with ${filters.length} filter${filters.length === 1 ? '' : 's'} applied`);
    }
    if (how.length) {
      sentences.push(`It is ${how.join(', ')}.`);
    }
  }

  if (typeof input.rowCount === 'number') {
    sentences.push(
      `The result has ${input.rowCount.toLocaleString()} row${input.rowCount === 1 ? '' : 's'}.`,
    );
  }

  return sentences.join(' ');
}
