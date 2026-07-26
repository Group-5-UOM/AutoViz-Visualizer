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

/**
 * Map the agent's chart results onto canvas widgets.
 *
 * Results without a `vega_lite_spec` (a plan that failed before charting) are
 * skipped — their error text still reaches the user through the chat answer.
 * `existingCount` continues the canvas layout below whatever is already placed.
 */
export function widgetsFromAgent(
  charts: AgentChartResult[],
  existingCount: number,
  makeId: () => string,
): ChartWidget[] {
  return charts
    .filter((chart) => chart.vega_lite_spec)
    .map((chart, i) => ({
      id: makeId(),
      title: titleFor(chart.task),
      explanation: explanationFor(chart),
      // The backend already sizes specs with width/height "container", so the
      // spec reflows with the widget instead of needing a re-embed.
      vegaLiteSpec: chart.vega_lite_spec as Record<string, unknown>,
      ...placement(existingCount + i),
    }));
}
