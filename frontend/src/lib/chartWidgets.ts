import type { AgentChartResult } from './agent';
import type { ChartWidget } from '../types/dashboard';

/** Canvas layout for newly-placed widgets — two columns, flowing downward. */
const COLUMNS = 2;
const CARD_W = 400;
const CARD_H = 280;
const GAP_X = 20;
const GAP_Y = 40;
const ORIGIN = 24;

function placement(index: number) {
  const col = index % COLUMNS;
  const row = Math.floor(index / COLUMNS);
  return {
    x: ORIGIN + col * (CARD_W + GAP_X),
    y: ORIGIN + row * (CARD_H + GAP_Y),
    width: CARD_W,
    height: CARD_H,
  };
}

/**
 * After a clarification, the planner appends its bookkeeping to the task —
 * "…sorted descending. [Resolved constraints: measure by mean of `x`]". That
 * belongs in the explanation, not in a card header, so it is stripped here.
 */
function titleFor(task: string): string {
  const trimmed = task.replace(/\s*\[Resolved constraints:[^\]]*\]\s*$/i, '').trim();
  if (!trimmed) return 'Chart';
  return trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
}

/** The stripped bookkeeping, reworded for the explanation line. */
function resolvedConstraints(task: string): string | null {
  const match = task.match(/\[Resolved constraints:\s*([^\]]*)\]/i);
  const detail = match?.[1]?.trim();
  return detail ? `Resolved: ${detail}` : null;
}

/**
 * The line shown under a selected chart: what was computed, plus anything the
 * backend flagged. Warnings and partial-run errors are surfaced here rather
 * than dropped — they explain charts that look wrong at a glance (too many
 * colour categories, a fallback chart after a failed recommendation).
 */
function explanationFor(chart: AgentChartResult): string {
  const parts: string[] = [];

  const rows = chart.result?.row_count;
  const type = chart.chart_spec?.type;
  if (typeof rows === 'number' && type) {
    parts.push(`${rows.toLocaleString()} row${rows === 1 ? '' : 's'} • ${type} chart`);
  } else if (typeof rows === 'number') {
    parts.push(`${rows.toLocaleString()} row${rows === 1 ? '' : 's'}`);
  } else if (type) {
    parts.push(`${type} chart`);
  }

  const resolved = resolvedConstraints(chart.task);
  if (resolved) parts.push(resolved);

  if (chart.status === 'partial') {
    parts.push('Partial result — some steps did not complete.');
  }
  parts.push(...(chart.warnings ?? []));
  parts.push(...(chart.errors ?? []));

  return parts.join(' — ') || 'Generated from your request.';
}

export interface AppliedCharts {
  /** The canvas, with replacements applied in place and new charts appended. */
  widgets: ChartWidget[];
  /** What to select and link the chat reply to; null if nothing was charted. */
  focusId: string | null;
  /** How many new widgets were placed, for the caller's layout counter. */
  placed: number;
}

/**
 * Fold the agent's chart results into the canvas.
 *
 * A result carrying the `chart_id` of a widget already on the canvas is that
 * widget, changed — a refinement like "make it a line chart". It is updated
 * where it sits, keeping its position, size, saved-chart row and any styling the
 * user applied; only what the agent recomputed is replaced. Anything else is a
 * new chart and gets a new card. A refinement whose card the user has since
 * deleted matches nothing and appends, which is the right way to fail.
 *
 * Results without a `vega_lite_spec` (a plan that failed before charting) are
 * skipped — their error text still reaches the user through the chat answer.
 * `existingCount` continues the canvas layout below whatever is already placed.
 */
export function applyAgentCharts(
  existing: ChartWidget[],
  charts: AgentChartResult[],
  existingCount: number,
  makeId: () => string,
): AppliedCharts {
  const usable = charts.filter((chart) => chart.vega_lite_spec);
  const replacements = new Map<string, AgentChartResult>();
  const additions: AgentChartResult[] = [];

  for (const chart of usable) {
    const target =
      chart.chart_id && existing.find((w) => w.agentChartId === chart.chart_id);
    if (target) replacements.set(target.id, chart);
    else additions.push(chart);
  }

  const widgets = existing.map((widget) => {
    const chart = replacements.get(widget.id);
    if (!chart) return widget;
    return {
      ...widget,
      title: titleFor(chart.task),
      explanation: explanationFor(chart),
      vegaLiteSpec: chart.vega_lite_spec as Record<string, unknown>,
      // The spec changed under a widget that may already be saved, which is the
      // one thing autosave cannot see for itself.
      specVersion: (widget.specVersion ?? 0) + 1,
    };
  });

  const created = additions.map((chart, i) => ({
    id: makeId(),
    agentChartId: chart.chart_id,
    title: titleFor(chart.task),
    explanation: explanationFor(chart),
    // The backend already sizes specs with width/height "container", so the
    // spec reflows with the widget instead of needing a re-embed.
    vegaLiteSpec: chart.vega_lite_spec as Record<string, unknown>,
    ...placement(existingCount + i),
  }));

  // Focus follows the first chart the agent produced, whether it landed on an
  // existing card or a new one — "view on canvas" has to point at what changed.
  const first = usable[0];
  const focusId =
    (first &&
      (widgets.find((w) => replacements.get(w.id) === first)?.id ??
        created[additions.indexOf(first)]?.id)) ||
    null;

  return { widgets: [...widgets, ...created], focusId, placed: created.length };
}
