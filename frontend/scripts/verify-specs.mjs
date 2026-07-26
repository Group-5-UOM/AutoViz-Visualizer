/**
 * Render every generated spec through the real Vega-Lite compiler and Vega
 * runtime, then assert what it actually drew (Docs/13 §6).
 *
 * The Python suite checks spec *structure*. That cannot tell you the spec
 * compiles, that the theme reached the marks, or that grouped bars grouped
 * rather than silently stacked — all of which are one-property mistakes with no
 * structural symptom. Two real bugs reached main-adjacent code and were caught
 * here rather than by unit tests.
 *
 *   python backend/scripts/emit_reference_specs.py
 *   npm run verify:specs
 */
import { compile } from 'vega-lite';
import * as vega from 'vega';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const SPEC_FILE = resolve(HERE, '../../backend/exports/_reference_specs.json');

const BLUE_RAMP_LIGHTEST = [205, 226, 251]; // #cde2fb

/** Compile + run a spec at a fixed size, returning its scenegraph marks. */
async function render(spec) {
  const logs = [];
  const logger = {
    level() { return this; },
    error(...a) { logs.push(`ERROR ${a.join(' ')}`); return this; },
    warn(...a) { logs.push(`WARN ${a.join(' ')}`); return this; },
    info() { return this; }, debug() { return this; },
  };
  // Container sizing resolves to nothing headless, so pin a size to measure against.
  const { spec: vgSpec } = compile({ ...spec, width: 400, height: 300 }, { logger });
  const view = new vega.View(vega.parse(vgSpec), { renderer: 'none' });
  const svg = await view.runAsync().then((v) => v.toSVG());

  const byType = {};
  const dataText = []; // text drawn from the data, as opposed to axis/legend chrome
  (function walk(item) {
    if (!item) return;
    if (item.marktype && item.items) {
      (byType[item.marktype] ??= []).push(...item.items);
      // Axis ticks and legend entries are text too; only role 'mark' is ours.
      if (item.marktype === 'text' && item.role === 'mark') dataText.push(...item.items);
    }
    (item.items || []).forEach(walk);
  })(view.scenegraph().root);
  view.finalize();

  return { svg, byType, dataText, errors: logs.filter((l) => l.startsWith('ERROR')) };
}

const rgb = (fill) => (String(fill).match(/\d+/g) || []).map(Number);
const isBlueish = (fill) => { const [r, g, b] = rgb(fill); return b > r && b >= g; };

/** name -> extra assertions beyond "compiles and draws something". */
const CHECKS = {
  grouped_bar: ({ byType }) => {
    const bars = byType.rect ?? [];
    const widths = new Set(bars.map((b) => Math.round(b.width)));
    const atBaseline = bars.filter((b) => Math.round(b.y2) === 300).length;
    // Grouped: each series gets a slice of the band and every bar starts at the
    // baseline. Stacked would be full-band width with contiguous segments.
    if (widths.size !== 1 || [...widths][0] >= 100) return `bars are full-band (${[...widths]}) — not grouped`;
    if (atBaseline !== bars.length) return `only ${atBaseline}/${bars.length} bars sit on the baseline — stacked`;
    return null;
  },
  stacked_bar: ({ byType }) => {
    const bars = byType.rect ?? [];
    const atBaseline = bars.filter((b) => Math.round(b.y2) === 300).length;
    if (atBaseline === bars.length) return 'every bar sits on the baseline — not stacked';
    return null;
  },
  donut: ({ byType }) => {
    const arcs = byType.arc ?? [];
    if (!arcs.length || arcs.some((a) => !(a.innerRadius > 0))) return 'no inner radius — rendered as a pie';
    return null;
  },
  pie: ({ byType }) => {
    const arcs = byType.arc ?? [];
    if (arcs.some((a) => a.innerRadius > 0)) return 'has an inner radius — rendered as a donut';
    return null;
  },
  heatmap: ({ byType }) => {
    const cells = byType.rect ?? [];
    const blue = cells.filter((c) => isBlueish(c.fill)).length;
    if (blue < cells.length - 1) return `only ${blue}/${cells.length} cells on the blue ramp — default scheme leaked through`;
    const lightest = cells.some((c) => rgb(c.fill).every((v, i) => Math.abs(v - BLUE_RAMP_LIGHTEST[i]) < 12));
    if (!lightest) return 'ramp does not reach its lightest step';
    return null;
  },
  boxplot: ({ byType }) => {
    // Composite mark: Vega-Lite throws on selection params, so it must have none.
    if (!(byType.rect ?? []).length) return 'no boxes drawn';
    if (!(byType.rule ?? []).length) return 'no whiskers drawn';
    return null;
  },
};

/**
 * Direct labels (Docs/13 §5) must actually reach the canvas — a text layer that
 * compiles but draws nothing discharges no accessibility obligation. Each entry
 * is the set of strings that must appear as rendered text, beyond axis ticks.
 */
const EXPECTED_LABELS = {
  bar: ['300', '1,200', '700'],           // values above each bar
  bar_ranking: ['300', '1,200', '700'],
  grouped_bar: null,                      // values; checked by count below
  heatmap: null,                          // cell values; checked by count below
  line_color: ['web', 'store'],           // series name at each line end
  donut: ['north', 'south', 'east'],      // category beside each slice
  pie: ['north', 'south', 'east'],
};
const LABEL_COUNTS = { grouped_bar: 9, heatmap: 9 }; // one per bar / per cell

// Ink a label may legitimately wear: secondary ink, or white where it sits on
// top of a dark heatmap cell. Never a series hue — that is the colour-alone
// dependency direct labels exist to remove.
const LABEL_INK = ['#60636c', '#ffffff'];

function labelCheck(name, { dataText }) {
  const wanted = EXPECTED_LABELS[name];
  const counted = LABEL_COUNTS[name];
  if (wanted === undefined && counted === undefined) return null;

  const drawn = dataText.map((t) => String(t.text));
  if (wanted) {
    const missing = wanted.filter((w) => !drawn.includes(w));
    if (missing.length) {
      return `labels missing from the canvas: ${missing.join(', ')} (drew: ${drawn.join('|') || 'nothing'})`;
    }
  }
  if (counted !== undefined && drawn.length < counted) {
    return `only ${drawn.length} data labels drawn, expected >= ${counted}`;
  }
  const tinted = dataText.filter((t) => t.fill && !LABEL_INK.includes(String(t.fill).toLowerCase()));
  if (tinted.length) {
    return `labels wear a non-ink colour (${[...new Set(tinted.map((t) => t.fill))].join(', ')})`;
  }
  return null;
}

/**
 * The table view reads its rows straight out of the spec (`lib/specData.ts`),
 * so every generated spec has to carry them inline. If a chart type ever stops
 * doing that, its accessible counterpart silently disappears with no error.
 */
function inlineRowsCheck(spec) {
  const values = spec?.data?.values;
  if (!Array.isArray(values) || values.length === 0) return 'carries no inline rows — table view would be unavailable';
  if (typeof values[0] !== 'object' || values[0] === null) return 'inline rows are not objects — table view cannot column them';
  return null;
}

/**
 * Brushable charts (Docs/13 A6) must expose the signal the frontend listens to,
 * and dragging it must actually dim what falls outside. Driving the extent
 * signals is what a real drag does, so this exercises the same path.
 */
const BRUSHABLE = {
  scatter: { mark: 'symbol', fields: { a: [2, 5], b: [0, 12] } },
  histogram: { mark: 'rect', fields: { price: [90, 210] } },
};

async function brushCheck(name, spec) {
  const expected = BRUSHABLE[name];
  if (!expected) return null;

  const { spec: vgSpec } = compile({ ...spec, width: 400, height: 300 });
  const view = new vega.View(vega.parse(vgSpec), { renderer: 'none' });
  await view.runAsync();

  // A spec with no interaction at all compiles without a signals array.
  const signals = new Set((vgSpec.signals ?? []).map((s) => s.name));
  if (!signals.has('autoviz_brush')) { view.finalize(); return 'no autoviz_brush signal — the table view could not follow a selection'; }

  const marksOf = () => {
    const found = [];
    (function walk(item) {
      if (!item) return;
      if (item.marktype === expected.mark && item.items) found.push(...item.items);
      (item.items || []).forEach(walk);
    })(view.scenegraph().root);
    return found;
  };

  const before = marksOf().length;
  for (const [field, [lo, hi]] of Object.entries(expected.fields)) {
    if (!signals.has(`autoviz_brush_${field}`)) {
      view.finalize();
      return `brush does not span '${field}' — its extent would not name a column the table can index`;
    }
    view.signal(`autoviz_brush_${field}`, [lo, hi]);
  }
  await view.runAsync();

  const dimmed = marksOf().filter((m) => m.opacity !== undefined && m.opacity < 1).length;
  view.finalize();
  if (!before) return 'nothing drawn to brush';
  if (!dimmed) return 'brushing dimmed nothing — the selection has no visible effect';
  if (dimmed === before) return 'brushing dimmed everything — nothing reads as selected';
  return null;
}

/** Every chart must use the palette, not Vega's stock tableau10. */
const TABLEAU = ['#4c78a8', '#f58518', '#e45756', '#72b7b2', '#54a24b'];
function paletteCheck({ byType }) {
  const fills = Object.values(byType).flat()
    .flatMap((i) => [i.fill, i.stroke]).filter(Boolean).map(String);
  const hex = fills.map((f) => {
    if (f.startsWith('#')) return f.toLowerCase();
    const [r, g, b] = rgb(f);
    return Number.isFinite(r) ? '#' + [r, g, b].map((v) => v.toString(16).padStart(2, '0')).join('') : '';
  });
  if (hex.some((h) => TABLEAU.includes(h))) return 'renders a tableau10 colour — theme did not apply';
  return null;
}

const specs = JSON.parse(readFileSync(SPEC_FILE, 'utf8'));
let failed = 0;
for (const [name, spec] of Object.entries(specs)) {
  const problems = [];
  try {
    const result = await render(spec);
    if (result.errors.length) problems.push(...result.errors);
    if (result.svg.length < 400) problems.push('rendered empty');
    const marks = Object.values(result.byType).flat().length;
    if (!marks) problems.push('no marks in the scenegraph');

    const pal = paletteCheck(result);
    if (pal) problems.push(pal);
    const lbl = labelCheck(name, result);
    if (lbl) problems.push(lbl);
    const rows = inlineRowsCheck(spec);
    if (rows) problems.push(rows);
    const brush = await brushCheck(name, spec);
    if (brush) problems.push(brush);
    const extra = CHECKS[name]?.(result);
    if (extra) problems.push(extra);

    if (problems.length) { failed++; console.log(`FAIL  ${name.padEnd(14)} ${problems.join('; ')}`); }
    else console.log(`ok    ${name.padEnd(14)} marks=${marks}`);
  } catch (e) {
    failed++;
    console.log(`THROW ${name.padEnd(14)} ${e.message.split('\n')[0].slice(0, 120)}`);
  }
}

console.log(failed
  ? `\n${failed}/${Object.keys(specs).length} specs failed verification`
  : `\nall ${Object.keys(specs).length} specs compile, render and match their intended geometry`);
process.exit(failed ? 1 : 0);
