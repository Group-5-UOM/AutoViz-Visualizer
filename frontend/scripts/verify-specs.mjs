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
// A spec file can be passed in, which is how the mutation runs work: emit a set
// with one modifier deliberately dropped from each sub-type, point this at it,
// and every check that matters must go red. A check that stays green on the
// mutant is not testing anything.
const SPEC_FILE = process.argv[2]
  ? resolve(process.cwd(), process.argv[2])
  : resolve(HERE, '../../backend/exports/_reference_specs.json');

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

  const byType = {};   // everything drawn, chrome included — for paletteCheck
  const marks = {};    // only role 'mark': the data itself
  const groups = [];   // one entry per mark group, so panels stay distinguishable
  const dataText = []; // text drawn from the data, as opposed to axis/legend chrome
  (function walk(item) {
    if (!item) return;
    if (item.marktype && item.items) {
      (byType[item.marktype] ??= []).push(...item.items);
      // Gridlines, ticks and axis domains are all `rule` marks, and legend keys
      // are `symbol` marks. Reading them as data is how a check ends up passing
      // on a chart that drew no data at all — the failure mode Docs/13 records
      // for the label check, repeated for every other geometry assertion.
      // A brush renders two rects of its own (`autoviz_brush_brush_bg` and
      // `autoviz_brush_brush`), role 'mark' and zero-sized at rest. They are
      // interaction chrome, and counting them as data made a horizontal
      // histogram look like it had bars of two different heights.
      if (item.role === 'mark' && !String(item.name).startsWith('autoviz_')) {
        (marks[item.marktype] ??= []).push(...item.items);
        // Mark *groups* are kept apart as well as pooled: a facet draws one
        // group per panel and a stack one per band, and "did every band fill
        // the plot?" cannot be asked of a flattened list.
        groups.push({ marktype: item.marktype, items: item.items });
        if (item.marktype === 'text') dataText.push(...item.items);
      }
    }
    (item.items || []).forEach(walk);
  })(view.scenegraph().root);
  view.finalize();

  return { svg, byType, marks, groups, dataText, errors: logs.filter((l) => l.startsWith('ERROR')) };
}

const rgb = (fill) => (String(fill).match(/\d+/g) || []).map(Number);
const isBlueish = (fill) => { const [r, g, b] = rgb(fill); return b > r && b >= g; };

/**
 * The geometric signature of a chart turned on its side: every rect shares the
 * band thickness (height) and differs along the value axis (width). The
 * vertical form is the exact transpose, so this fails on it either way round.
 *
 * `fromLeft` additionally pins the marks to the value axis's zero — a bar has
 * to grow from its baseline, and a horizontal one whose bars float would be
 * measuring lengths from nowhere.
 */
function onItsSide(rects, { fromLeft = false } = {}) {
  if (!rects.length) return 'nothing drawn';
  const widths = new Set(rects.map((r) => Math.round(r.width)));
  const heights = new Set(rects.map((r) => Math.round(r.height)));
  if (heights.size !== 1) return `mark heights vary (${[...heights]}) — still vertical`;
  if (widths.size < 2) return `mark widths are all ${[...widths]} — the value is not on x`;
  if (fromLeft && rects.some((r) => Math.round(r.x) !== 0)) {
    return 'marks do not start at the left baseline';
  }
  return null;
}

/**
 * Segment count of the longest path in the SVG — the data line, since gridlines
 * and axis domains are two-point paths.
 *
 * Interpolation is the one modifier with no scenegraph signature: a stepped line
 * and a straight one hold the identical twelve data points, and only the path
 * drawn between them differs. A step inserts a corner per interval, so it lands
 * at roughly twice the segments.
 */
function longestPathSegments(svg) {
  const paths = [...svg.matchAll(/ d="([^"]+)"/g)].map((m) => m[1]);
  return paths.reduce((best, d) => Math.max(best, (d.match(/[LHV]/g) || []).length), 0);
}

/** name -> extra assertions beyond "compiles and draws something". */
const CHECKS = {
  grouped_bar: ({ marks }) => {
    const bars = marks.rect ?? [];
    const widths = new Set(bars.map((b) => Math.round(b.width)));
    const atBaseline = bars.filter((b) => Math.round(b.y2) === 300).length;
    // Grouped: each series gets a slice of the band and every bar starts at the
    // baseline. Stacked would be full-band width with contiguous segments.
    if (widths.size !== 1 || [...widths][0] >= 100) return `bars are full-band (${[...widths]}) — not grouped`;
    if (atBaseline !== bars.length) return `only ${atBaseline}/${bars.length} bars sit on the baseline — stacked`;
    return null;
  },
  stacked_bar: ({ marks }) => {
    const bars = marks.rect ?? [];
    const atBaseline = bars.filter((b) => Math.round(b.y2) === 300).length;
    if (atBaseline === bars.length) return 'every bar sits on the baseline — not stacked';
    return null;
  },
  donut: ({ marks }) => {
    const arcs = marks.arc ?? [];
    if (!arcs.length || arcs.some((a) => !(a.innerRadius > 0))) return 'no inner radius — rendered as a pie';
    return null;
  },
  pie: ({ marks }) => {
    const arcs = marks.arc ?? [];
    if (arcs.some((a) => a.innerRadius > 0)) return 'has an inner radius — rendered as a donut';
    return null;
  },
  heatmap: ({ marks }) => {
    const cells = marks.rect ?? [];
    const blue = cells.filter((c) => isBlueish(c.fill)).length;
    if (blue < cells.length - 1) return `only ${blue}/${cells.length} cells on the blue ramp — default scheme leaked through`;
    const lightest = cells.some((c) => rgb(c.fill).every((v, i) => Math.abs(v - BLUE_RAMP_LIGHTEST[i]) < 12));
    if (!lightest) return 'ramp does not reach its lightest step';
    return null;
  },
  boxplot: ({ marks }) => {
    // Composite mark: Vega-Lite throws on selection params, so it must have none.
    // Read off role 'mark': every gridline is a rule, so the whisker check
    // passed on any chart at all until the role filter existed.
    if (!(marks.rect ?? []).length) return 'no boxes drawn';
    if (!(marks.rule ?? []).length) return 'no whiskers drawn';
    return null;
  },

  // --- sub-types (Docs/13 §11) ----------------------------------------------
  // A modifier that silently does nothing renders a perfectly good chart of the
  // wrong kind, which is the whole reason these are scenegraph assertions and
  // not structural ones. Each check below is the geometric difference the
  // modifier is *for* — a swapped axis, a stack that reaches the top, a
  // substituted mark — so deleting the modifier fails the check.

  bar_horizontal: ({ marks }) => onItsSide(marks.rect ?? [], { fromLeft: true }),
  bar_stacked_100: ({ groups }) => {
    const bands = groups.filter((g) => g.marktype === 'rect');
    if (!bands.length) return 'no bars drawn';
    // Normalised: every band fills the plot exactly, whatever its raw total.
    // Un-normalised, only the largest band reaches the top — _GRID's three
    // bands total 12, 39 and 66, so they would stand at 55, 177 and 300.
    const totals = bands.map((g) =>
      Math.round(g.items.reduce((sum, b) => sum + b.height, 0)));
    if (totals.some((t) => Math.abs(t - 300) > 2)) {
      return `bands stand at ${totals} — not every column fills the plot, so not normalised`;
    }
    return null;
  },
  bar_error: ({ marks }) => {
    if (!(marks.rect ?? []).length) return 'no bars drawn';
    // The errorbar composite draws rules. Filtered to role 'mark', because
    // every gridline in the chart is a rule too.
    if (!(marks.rule ?? []).length) return 'no error bars drawn';
    return null;
  },
  bar_faceted: ({ marks, svg }) => {
    const bars = marks.rect ?? [];
    if (bars.length !== 28) return `drew ${bars.length} bars for 4 regions x 7 months`;
    // Panel coordinates are relative to their own panel, so geometry alone
    // cannot tell four panels from one. What can is the header Vega-Lite draws
    // per panel: without the facet there is one frame and no region named on it.
    const missing = ['north', 'south', 'east', 'west'].filter((r) => !svg.includes(`>${r}<`));
    if (missing.length) return `panels not headed by region (${missing.join(', ')} absent) — the facet did not split`;
    return null;
  },
  grouped_bar_horizontal: ({ marks }) => {
    const bars = marks.rect ?? [];
    if (!bars.length) return 'no bars drawn';
    const heights = new Set(bars.map((b) => Math.round(b.height)));
    if (heights.size !== 1) return `bar heights vary (${[...heights]}) — still vertical`;
    if (bars.some((b) => Math.round(b.x) !== 0)) return 'bars do not start at the left baseline';
    // Grouped, not stacked: each series takes a slice of the band.
    if ([...heights][0] >= 100) return `bars are full-band (${[...heights]}) — not grouped`;
    return null;
  },
  line_step: ({ svg }) => {
    // The scenegraph holds the same 12 data points either way — only the path
    // between them changes, so this has to read the rendered path itself.
    const segments = longestPathSegments(svg);
    if (segments < 15) return `line path has ${segments} segments — not stepped (linear would be ~11)`;
    return null;
  },
  line_points: ({ marks }) => (marks.symbol ?? []).length ? null : 'no point markers drawn',
  line_error_band: ({ marks }) => {
    if (!(marks.line ?? []).length) return 'no line drawn';
    if (!(marks.area ?? []).length) return 'no confidence band drawn';
    return null;
  },
  area_stacked: ({ groups }) => {
    const bands = groups.filter((g) => g.marktype === 'area');
    if (bands.length < 2) return `drew ${bands.length} area(s) — the two series did not separate`;
    // Stacked from zero: the lower series is pinned to the plot floor at every
    // point, and the upper one rides on top of it. Overlaid, both would sit on
    // the floor; centred, neither would.
    const pinned = bands.filter((g) => g.items.every((p) => Math.round(p.y2) >= 299));
    if (pinned.length !== 1) {
      return `${pinned.length} series sit on the floor — expected exactly the lower one`;
    }
    return null;
  },
  area_streamgraph: ({ groups }) => {
    const bands = groups.filter((g) => g.marktype === 'area');
    if (bands.length < 2) return `drew ${bands.length} area(s) — the two series did not separate`;
    // Centred: the baseline wanders, so no series has a constant floor. A point
    // may still touch the plot edge at the widest month — that is the domain
    // extreme, not a baseline — so this asks whether y2 *varies*, not where it is.
    const flat = bands.filter((g) => new Set(g.items.map((p) => Math.round(p.y2))).size === 1);
    if (flat.length) return `${flat.length} series has a flat baseline — stacked from zero, not centred`;
    return null;
  },
  scatter_bubble: ({ marks }) => {
    const pts = marks.symbol ?? [];
    if (!pts.length) return 'no points drawn';
    const sizes = new Set(pts.map((p) => Math.round(p.size)));
    if (sizes.size < 3) return `only ${sizes.size} distinct point size(s) — magnitude is not on size`;
    return null;
  },
  scatter_binned: ({ marks }) => {
    if ((marks.symbol ?? []).length) return 'still drawing individual points — not binned';
    const cells = marks.rect ?? [];
    if (!cells.length) return 'no bins drawn';
    if (!cells.some((c) => isBlueish(c.fill))) return 'bins are not on the blue ramp';
    return null;
  },
  histogram_density: ({ marks }) => {
    if ((marks.rect ?? []).length) return 'still drawing bars — the density curve did not replace them';
    if (!(marks.area ?? []).length) return 'no density curve drawn';
    return null;
  },
  histogram_cumulative: ({ marks }) => {
    const pts = (marks.area ?? []).slice().sort((a, b) => a.x - b.x);
    if (!pts.length) return 'no cumulative curve drawn';
    // A running count never falls. Screen y grows downwards, so it never rises.
    const rises = pts.slice(1).filter((p, i) => p.y > pts[i].y + 0.5).length;
    if (rises) return `curve falls back ${rises} time(s) — not a cumulative total`;
    return null;
  },
  histogram_horizontal: ({ marks }) => onItsSide(marks.rect ?? [], { fromLeft: true }),
  heatmap_calendar: ({ marks }) => {
    const cells = marks.rect ?? [];
    if (!cells.length) return 'no cells drawn';
    // Two granularities of the same date column: months across, days down.
    const cols = new Set(cells.map((c) => Math.round(c.x)));
    const rows = new Set(cells.map((c) => Math.round(c.y)));
    if (cols.size < 2) return 'only one column — the x time unit did not bucket';
    if (rows.size < 7) return `only ${rows.size} rows — the y time unit did not bucket`;
    return null;
  },
  boxplot_violin: ({ groups, marks }) => {
    if (!(marks.area ?? []).length) return 'no density areas drawn';
    if ((marks.rule ?? []).length) return 'whiskers drawn — still a box plot';
    // One panel per class, butted together: three classes, three mark groups.
    const panels = groups.filter((g) => g.marktype === 'area').length;
    if (panels !== 3) return `drew ${panels} densit(ies) for 3 classes — not one panel each`;
    return null;
  },
  boxplot_strip: ({ marks }) => {
    if ((marks.rule ?? []).length) return 'whiskers drawn — still a box plot';
    // One tick per row, not one box per group: 27 rows across 3 groups.
    const ticks = marks.rect ?? [];
    if (ticks.length < 20) return `only ${ticks.length} ticks — a strip draws every value`;
    return null;
  },
  boxplot_points: ({ marks }) => {
    if (!(marks.rect ?? []).length) return 'no boxes drawn';
    const pts = marks.symbol ?? [];
    if (!pts.length) return 'no raw points overlaid';
    // Jittered across the band, not stacked in a line down the middle.
    const xs = new Set(pts.map((p) => Math.round(p.x)));
    if (xs.size < 5) return `points sit on ${xs.size} x position(s) — not jittered`;
    return null;
  },
  // The median marker is a 1px-wide rect, so this reads the shared band
  // thickness rather than "wider than tall" — which the marker fails on either
  // orientation.
  boxplot_horizontal: ({ marks }) => onItsSide(marks.rect ?? []),

  // --- awkward data ---------------------------------------------------------
  // Three defects that structural tests could never see, because the specs were
  // valid. Only the scenegraph showed what was actually drawn.

  edge_line_one_point: ({ marks }) => {
    // A line through one point is a zero-length path: axes, and nothing else.
    // The point overlay is the only thing that makes the datum exist on screen.
    if (!(marks.symbol ?? []).length) return 'one-point line drew no point — the panel is blank';
    return null;
  },
  edge_bar_all_null: ({ marks }) => {
    // The worst of the three. With every value null, Vega gave both bars the
    // full plot height, so an empty answer looked like two large equal ones.
    const bars = marks.rect ?? [];
    if (bars.length) return `drew ${bars.length} bar(s) for rows that have no values`;
    return null;
  },
  edge_bar_some_null: ({ marks }) => {
    // The null row is dropped (and disclosed in a notice); the other two must
    // survive at heights proportional to their values, not stretched to fill.
    const bars = marks.rect ?? [];
    if (bars.length !== 2) return `expected 2 bars for 2 plottable rows, drew ${bars.length}`;
    const heights = bars.map((b) => Math.round(b.height));
    if (heights[0] === heights[1]) return `bars are equal height (${heights}) — values 300 and 900 are not`;
    return null;
  },
};

/**
 * Specs that are *supposed* to draw nothing. Without this the generic "rendered
 * empty" and "carries no inline rows" checks would fail the very case whose
 * correct behaviour is emptiness — and the only way to pass them would be to
 * put the misleading bars back.
 */
const EMPTY_BY_DESIGN = new Set(['edge_bar_all_null']);

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
  // A horizontal bar still labels — off the end of each bar rather than above
  // it. This is the check that the placement followed the axis swap; before it
  // did, every value sat above its bar's own row, beside the wrong category.
  bar_horizontal: ['300', '1,200', '700'],
};
const LABEL_COUNTS = { grouped_bar: 9, heatmap: 9, grouped_bar_horizontal: 9 };

/**
 * Sub-types whose family labels but which must not, each for a reason recorded
 * on `Form.draws_labels`: stacked segments collide, an error mark's value is a
 * Vega-side mean the label would not be reading, and a facet panel is too
 * narrow to carry one. Asserting the *absence* matters as much as the presence
 * — a label layer that survived onto a stacked bar is unreadable overlap, and
 * nothing else here would notice it.
 */
const EXPECT_NO_LABELS = new Set([
  'bar_stacked_100', 'bar_error', 'bar_faceted', 'area_stacked',
  'area_streamgraph', 'scatter_bubble', 'histogram_density', 'boxplot_strip',
]);

// Ink a label may legitimately wear: secondary ink, or white where it sits on
// top of a dark heatmap cell. Never a series hue — that is the colour-alone
// dependency direct labels exist to remove.
const LABEL_INK = ['#60636c', '#ffffff'];

function labelCheck(name, { dataText }) {
  if (EXPECT_NO_LABELS.has(name)) {
    return dataText.length
      ? `drew ${dataText.length} data label(s) on a sub-type that must carry none`
      : null;
  }
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
  // A bubble is still a scatter: adding a size channel must not cost the brush.
  scatter_bubble: { mark: 'symbol', fields: { a: [2, 5], b: [0, 12] } },
  // Turning the histogram on its side moves the binned axis, and the brush has
  // to follow it — brushing the count axis would select on a derived value that
  // is in no row, so the table view would have nothing to filter by.
  histogram_horizontal: { mark: 'rect', fields: { price: [90, 210] } },
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
      if (item.marktype === expected.mark && item.role === 'mark' && item.items) {
        found.push(...item.items);
      }
      (item.items || []).forEach(walk);
    })(view.scenegraph().root);
    return found;
  };

  // Measured against the *resting* opacity, not against 1. A sub-type that is
  // translucent by design — a bubble at 0.7, a strip of ticks — has every mark
  // below 1 before anything is brushed, and comparing to 1 reported the whole
  // chart as dimmed and the selection as invisible.
  const resting = marksOf().map((m) => (m.opacity === undefined ? 1 : m.opacity));
  const before = resting.length;
  for (const [field, [lo, hi]] of Object.entries(expected.fields)) {
    if (!signals.has(`autoviz_brush_${field}`)) {
      view.finalize();
      return `brush does not span '${field}' — its extent would not name a column the table can index`;
    }
    view.signal(`autoviz_brush_${field}`, [lo, hi]);
  }
  await view.runAsync();

  const after = marksOf().map((m) => (m.opacity === undefined ? 1 : m.opacity));
  const dimmed = after.filter((o, i) => o < resting[i] - 1e-6).length;
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
    const empty = EMPTY_BY_DESIGN.has(name);
    if (result.errors.length) problems.push(...result.errors);
    if (!empty && result.svg.length < 400) problems.push('rendered empty');
    const marks = Object.values(result.byType).flat().length;
    if (!empty && !marks) problems.push('no marks in the scenegraph');

    const pal = paletteCheck(result);
    if (pal) problems.push(pal);
    const lbl = labelCheck(name, result);
    if (lbl) problems.push(lbl);
    const rows = empty ? null : inlineRowsCheck(spec);
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
