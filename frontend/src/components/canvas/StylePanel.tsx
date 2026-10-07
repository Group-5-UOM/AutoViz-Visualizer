import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { Palette, RotateCcw, Trash2, X } from 'lucide-react';
import { useEscapeToClose } from '../../hooks/useEscapeToClose';
import type { ChartFont, ChartStyle, ChartWidget } from '../../types/dashboard';
import { specSeries } from '../../lib/specData';
import './StylePanel.css';

/**
 * Direct controls for the same style block the natural-language editor writes.
 *
 * Both surfaces post to `POST /charts/style`; this one sends the block alone and
 * never reaches a model, which is what makes picking a colour instant and free.
 * "Make the bars orange" is a good way to say the easy 80%; `#7d3cff` is not,
 * and that is the gap this fills.
 */

/**
 * Presets, matching the theme's slot order. Duplicated from backend
 * `services/chart_theme.CATEGORICAL` on purpose: these are picker suggestions,
 * not the rendering source of truth — the theme is still baked in server-side,
 * so a drift here changes what is *offered*, never what an unstyled chart draws.
 */
const PRESETS = [
  '#2a78d6',
  '#eb6834',
  '#1baf7a',
  '#eda100',
  '#e87ba4',
  '#008300',
  '#4a3aa7',
  '#e34948',
];

const HEX = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

/**
 * Mirrors backend `schema/chart_style.FontFamily`. The labels are ours; the
 * values are the contract, so renaming one here breaks the patch, not the copy.
 */
const FONTS: { value: ChartFont; label: string }[] = [
  { value: 'sans', label: 'Sans (default)' },
  { value: 'system', label: 'System' },
  { value: 'serif', label: 'Serif' },
  { value: 'mono', label: 'Monospace' },
];

/**
 * Offered sizes, inside backend MIN_FONT_SIZE..MAX_FONT_SIZE. A discrete list
 * rather than a slider or a spinner: every change here is a request and a
 * re-render, and a slider would fire one per step of the drag.
 */
const FONT_SIZES = [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28];

/** Backend `chart_theme.BASE_FONT_SIZE` — what "Default" resolves to. */
const DEFAULT_FONT_SIZE = 11;

interface StylePanelProps {
  widget: ChartWidget;
  busy: boolean;
  /** Resolves to an error message when the block was rejected, else null. */
  onApply: (style: ChartStyle) => Promise<string | null>;
  onClose: () => void;
}

/** Same idea as backend `primary_layer` / `specData.primaryLayer`. */
function primaryLayer(spec: Record<string, unknown> | undefined): Record<string, unknown> {
  if (!spec) return {};
  const layers = spec.layer;
  if (Array.isArray(layers) && layers.length > 0 && layers[0] && typeof layers[0] === 'object') {
    return layers[0] as Record<string, unknown>;
  }
  return spec;
}

function readTitleText(title: unknown): string | null {
  if (typeof title === 'string' && title.trim()) return title;
  if (title && typeof title === 'object') {
    const text = (title as { text?: unknown }).text;
    if (typeof text === 'string' && text.trim()) return text;
  }
  return null;
}

/**
 * What the chart actually shows for title / axes.
 * Generated specs often omit explicit titles; Vega-Lite then uses the encoding
 * field name, and the card title is `widget.title` rather than `spec.title`.
 */
function inferredLabels(widget: ChartWidget): { title: string; x: string; y: string } {
  const style = widget.style ?? {};
  const spec = widget.vegaLiteSpec;
  const layer = primaryLayer(spec);
  const encoding = (layer.encoding ?? {}) as Record<string, unknown>;

  const channelLabel = (ch: unknown): string => {
    if (!ch || typeof ch !== 'object') return '';
    const enc = ch as { axis?: { title?: unknown }; title?: unknown; field?: unknown };
    return (
      readTitleText(enc.axis?.title) ??
      readTitleText(enc.title) ??
      (typeof enc.field === 'string' ? enc.field : '') ??
      ''
    );
  };

  return {
    title:
      (typeof style.title === 'string' && style.title) ||
      readTitleText(spec?.title) ||
      widget.title ||
      '',
    x:
      (typeof style.x_title === 'string' && style.x_title) ||
      channelLabel(encoding.x) ||
      '',
    y:
      (typeof style.y_title === 'string' && style.y_title) ||
      channelLabel(encoding.y) ||
      '',
  };
}

function ColorField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string | undefined;
  onChange: (hex: string | null) => void;
}) {
  const [text, setText] = useState(value ?? '');

  useEffect(() => setText(value ?? ''), [value]);

  const commit = (hex: string) => {
    const trimmed = hex.trim();
    if (!trimmed) return onChange(null);
    if (HEX.test(trimmed)) onChange(trimmed);
  };

  return (
    <div className="style-color-field">
      <span className="style-color-label">{label}</span>
      <div className="style-swatches">
        {PRESETS.map((hex) => (
          <button
            key={hex}
            type="button"
            className={`style-swatch ${value === hex ? 'is-active' : ''}`}
            style={{ background: hex }}
            title={hex}
            aria-label={`${label}: ${hex}`}
            aria-pressed={value === hex}
            onClick={() => onChange(hex)}
          />
        ))}
      </div>
      <div className="style-hex-row">
        <input
          type="text"
          className="style-hex"
          value={text}
          placeholder="#7d3cff"
          aria-label={`${label} hex code`}
          onChange={(e) => setText(e.target.value)}
          onBlur={() => commit(text)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commit(text);
          }}
        />
        {value && (
          <button type="button" className="style-reset" onClick={() => onChange(null)}>
            Reset
          </button>
        )}
      </div>
    </div>
  );
}

/** What the advanced editor shows for a block with no raw config yet. */
const CONFIG_EXAMPLE = `{
  "axis": { "gridDash": [4, 2], "labelAngle": 0 },
  "bar": { "cornerRadiusEnd": 4 },
  "background": "#fbfbfd"
}`;

function formatConfig(config: Record<string, unknown> | null | undefined): string {
  return config && Object.keys(config).length > 0 ? JSON.stringify(config, null, 2) : '';
}

function hasKeys(config: Record<string, unknown> | null | undefined): boolean {
  return Boolean(config && Object.keys(config).length > 0);
}

/** Every field the Style tab owns, cleared. `config` is the Advanced tab's. */
const CLEARED_STYLE: ChartStyle = {
  title: null,
  x_title: null,
  y_title: null,
  legend: null,
  labels: null,
  mark_color: null,
  series_colors: null,
  color_scheme: null,
  font: null,
  font_size: null,
};

type StyleTab = 'style' | 'advanced';

const TABS: { id: StyleTab; label: string }[] = [
  { id: 'style', label: 'Style' },
  { id: 'advanced', label: 'Advanced' },
];

/**
 * Whether the chart draws direct labels — a text layer beside its data layer.
 * The toggle is offered only then: on a scatter or a histogram it would be a
 * switch that does nothing.
 */
function hasDirectLabels(spec: Record<string, unknown>): boolean {
  const root = (spec.spec as Record<string, unknown> | undefined) ?? spec;
  const layers = Array.isArray(root.layer) ? (root.layer as Record<string, unknown>[]) : [];
  return layers.slice(1).some((layer) => {
    const mark = layer.mark;
    const kind = typeof mark === 'string' ? mark : (mark as { type?: string } | undefined)?.type;
    return kind === 'text';
  });
}

export function StylePanel({ widget, busy, onApply, onClose }: StylePanelProps) {
  const style = widget.style ?? {};
  const series = specSeries(widget.vegaLiteSpec);
  const labels = inferredLabels(widget);
  const hasConfig = hasKeys(style.config);

  // This panel has no sidebar entry to toggle it shut, and it stops pointer-down
  // so the canvas deselect cannot reach it either. With its close button gone,
  // Escape and the chart's palette button are the only ways out.
  useEscapeToClose(onClose);

  // Opens on Advanced only for a chart that already has a hand-written config —
  // that is where its owner last worked on it. Reset only on switching charts:
  // a config applied from the Style tab must not pull the user across tabs.
  const [tab, setTab] = useState<StyleTab>(hasConfig ? 'advanced' : 'style');
  const [tabFor, setTabFor] = useState(widget.id);
  if (tabFor !== widget.id) {
    setTabFor(widget.id);
    setTab(hasConfig ? 'advanced' : 'style');
  }

  // Text is edited locally and committed on blur or Enter: firing a request per
  // keystroke would be one round trip and one autosave per character typed.
  const [titles, setTitles] = useState({
    title: labels.title,
    x_title: labels.x,
    y_title: labels.y,
  });

  useEffect(() => {
    const next = inferredLabels(widget);
    setTitles({
      title: next.title,
      x_title: next.x,
      y_title: next.y,
    });
  }, [widget.id, widget.title, widget.style, widget.vegaLiteSpec]);

  // A rejected block is not a thrown error and not a changed chart — the spec
  // comes back untouched. Nothing here would show that on its own, so a failed
  // edit used to look identical to one the backend had never heard of. Kept per
  // tab, so the message sits beside the control that caused it.
  const [error, setError] = useState<string | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);

  // The advanced editor's draft, apart from the stored block until applied so a
  // half-typed object never reaches the chart.
  const [configText, setConfigText] = useState(formatConfig(style.config));
  useEffect(() => {
    setConfigText(formatConfig(widget.style?.config));
    setConfigError(null);
  }, [widget.id, widget.style?.config]);

  useEffect(() => setError(null), [widget.id]);

  // The block as the user last asked for it, ahead of what has rendered. Two
  // edits in quick succession — a label committed on blur by the very click
  // that picks a colour — each used to build on the same stale `style`, so the
  // second request carried no label and the axis title snapped back.
  const intended = useRef<ChartStyle>(style);
  const storedStyle = widget.style;
  useEffect(() => {
    intended.current = storedStyle ?? {};
  }, [widget.id, storedStyle]);

  // Always the whole block: the backend treats it as the widget's styling state,
  // not a diff, so an omitted field would read as a revert.
  const patch = async (change: ChartStyle) => {
    const next = { ...intended.current, ...change };
    intended.current = next;
    setError(await onApply(next));
  };

  const commitText = (key: 'title' | 'x_title' | 'y_title') => {
    const next = titles[key].trim();
    const current = intended.current[key];
    const stored = typeof current === 'string' ? current : null;
    const effective = key === 'title' ? labels.title : key === 'x_title' ? labels.x : labels.y;

    if (stored !== null) {
      if (next === stored) return;
      // Empty clears the override and restores the chart's natural label.
      patch({ [key]: next || null } as ChartStyle);
      return;
    }
    // No override yet — only persist when the user changed the shown default.
    if (!next || next === effective) return;
    patch({ [key]: next } as ChartStyle);
  };

  /**
   * Apply the advanced editor's JSON. Syntax is checked here so a typo never
   * costs a round trip; what the object may contain is the backend's call.
   */
  const applyConfig = async (text: string) => {
    const trimmed = text.trim();
    let config: Record<string, unknown> | null = null;
    if (trimmed) {
      let parsed: unknown;
      try {
        parsed = JSON.parse(trimmed);
      } catch (err) {
        setConfigError(err instanceof Error ? err.message : 'Not valid JSON.');
        return;
      }
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        setConfigError('The config must be a JSON object, like { "axis": { … } }.');
        return;
      }
      config = hasKeys(parsed as Record<string, unknown>)
        ? (parsed as Record<string, unknown>)
        : null;
    }
    const nextStyle = { ...intended.current, config };
    intended.current = nextStyle;
    setConfigError(await onApply(nextStyle));
  };

  const hasStyleOverrides = (Object.keys(CLEARED_STYLE) as (keyof ChartStyle)[]).some(
    (key) => style[key] !== undefined && style[key] !== null,
  );
  const configDirty = configText.trim() !== formatConfig(style.config).trim();

  const textField = (key: 'title' | 'x_title' | 'y_title', label: string) => (
    <label className="style-field">
      <span>{label}</span>
      <input
        type="text"
        value={titles[key]}
        disabled={busy}
        placeholder="Default"
        onChange={(e) => setTitles((prev) => ({ ...prev, [key]: e.target.value }))}
        onBlur={() => commitText(key)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') e.currentTarget.blur();
        }}
      />
    </label>
  );

  // Arrow keys move between tabs, as a tablist is expected to.
  const onTabKey = (e: KeyboardEvent) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    const i = TABS.findIndex((t) => t.id === tab);
    const next = TABS[(i + (e.key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length];
    setTab(next.id);
    document.getElementById(`style-tab-${next.id}`)?.focus();
  };

  return (
    <aside
      className="style-panel"
      aria-label={`Style options for ${widget.title}`}
      // The canvas deselects on pointer-down, which would close this panel the
      // moment anyone reached for a control in it.
      onPointerDown={(e) => e.stopPropagation()}
    >
      {/* Outside the scrolling body on purpose: the close control has to stay
          reachable at the top of a panel whose contents run past its height. */}
      <header className="style-panel-header">
        <Palette size={14} aria-hidden />
        <p className="style-panel-subject" title={widget.title}>
          Style · {widget.title}
        </p>
        <button
          type="button"
          className="style-panel-close"
          onClick={onClose}
          aria-label="Close style options"
          title="Close"
        >
          <X size={16} />
        </button>
      </header>

      <div className="style-tabs" role="tablist" aria-label="Styling mode" onKeyDown={onTabKey}>
        {TABS.map(({ id, label }) => (
          <button
            key={id}
            id={`style-tab-${id}`}
            type="button"
            role="tab"
            className="style-tab"
            aria-selected={tab === id}
            aria-controls={`style-tabpanel-${id}`}
            tabIndex={tab === id ? 0 : -1}
            onClick={() => setTab(id)}
          >
            {label}
            {id === 'advanced' && hasConfig && (
              <span className="style-tab-dot" title="This chart has a custom config" />
            )}
          </button>
        ))}
      </div>

      {tab === 'style' ? (
        <>
          <div
            className="style-panel-body"
            role="tabpanel"
            id="style-tabpanel-style"
            aria-labelledby="style-tab-style"
          >
            <p className="style-panel-hint">
              Changes apply as you make them. For anything not listed here, use the
              Advanced tab.
            </p>

            {error && (
              <p className="style-error" role="alert">
                {error}
              </p>
            )}

            <section className="style-section">
              <h4 className="style-section-label">Labels</h4>
              {textField('title', 'Title')}
              {textField('x_title', 'X-axis label')}
              {textField('y_title', 'Y-axis label')}
            </section>

            <section className="style-section">
              <h4 className="style-section-label">Text</h4>
              <label className="style-field">
                <span>Font</span>
                <select
                  value={style.font ?? ''}
                  disabled={busy}
                  onChange={(e) => patch({ font: (e.target.value || null) as ChartFont | null })}
                >
                  <option value="">Default</option>
                  {FONTS.map(({ value, label }) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="style-field">
                <span>Text size</span>
                <select
                  value={style.font_size ?? ''}
                  disabled={busy}
                  onChange={(e) =>
                    patch({ font_size: e.target.value ? Number(e.target.value) : null })
                  }
                >
                  <option value="">Default ({DEFAULT_FONT_SIZE} px)</option>
                  {FONT_SIZES.map((size) => (
                    <option key={size} value={size}>
                      {size} px
                    </option>
                  ))}
                </select>
              </label>
            </section>

            <section className="style-section">
              <h4 className="style-section-label">Colour</h4>
              {series.length > 0 ? (
                <>
                  {series.map((name) => (
                    <ColorField
                      key={name}
                      label={name}
                      value={style.series_colors?.[name]}
                      onChange={(hex) => {
                        const next = { ...(style.series_colors ?? {}) };
                        if (hex) next[name] = hex;
                        else delete next[name];
                        patch({ series_colors: Object.keys(next).length ? next : null });
                      }}
                    />
                  ))}
                  <label className="style-toggle">
                    <input
                      type="checkbox"
                      checked={style.legend !== false}
                      disabled={busy}
                      onChange={(e) => patch({ legend: e.target.checked ? null : false })}
                    />
                    <span>Show legend</span>
                  </label>
                </>
              ) : (
                <ColorField
                  label="Chart colour"
                  value={style.mark_color ?? undefined}
                  onChange={(hex) => patch({ mark_color: hex })}
                />
              )}
              {hasDirectLabels(widget.vegaLiteSpec) && (
                <label className="style-toggle">
                  <input
                    type="checkbox"
                    checked={style.labels !== false}
                    disabled={busy}
                    onChange={(e) => patch({ labels: e.target.checked ? null : false })}
                  />
                  <span>Show labels on the chart</span>
                </label>
              )}
            </section>
          </div>

          <footer className="style-panel-footer">
            <button
              type="button"
              className="style-btn style-btn-ghost"
              disabled={busy || !hasStyleOverrides}
              onClick={() => void patch(CLEARED_STYLE)}
              title="Clear every option on this tab and go back to the theme"
            >
              <RotateCcw size={14} />
              Reset all
            </button>
          </footer>
        </>
      ) : (
        <>
          <div
            className="style-panel-body"
            role="tabpanel"
            id="style-tabpanel-advanced"
            aria-labelledby="style-tab-advanced"
          >
            {/* A raw Vega-Lite `config` for the long tail the Style tab does not
                cover. `config` rather than the whole spec on purpose: it holds
                appearance and nothing else, so no edit here can change a
                number, and the editor never has to show the inlined rows. */}
            <p className="style-panel-hint">
              Any{' '}
              <a
                href="https://vega.github.io/vega-lite/docs/config.html"
                target="_blank"
                rel="noreferrer"
              >
                Vega-Lite config
              </a>{' '}
              property — gridlines, corner radius, label angle, background. Applied on
              top of the Style tab, so it wins where both set something.{' '}
              <code>null</code> removes a default.
            </p>

            <label className="style-config-field">
              <span className="style-section-label">Vega-Lite config</span>
              <textarea
                className="style-config-editor"
                value={configText}
                spellCheck={false}
                disabled={busy}
                placeholder={CONFIG_EXAMPLE}
                aria-invalid={Boolean(configError)}
                onChange={(e) => {
                  setConfigText(e.target.value);
                  setConfigError(null);
                }}
                onKeyDown={(e) => {
                  // The canvas listens for keys (delete a selected chart,
                  // Escape); none of that should fire while typing JSON.
                  e.stopPropagation();
                  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) void applyConfig(configText);
                }}
              />
            </label>

            {configError && (
              <p className="style-error" role="alert">
                {configError}
              </p>
            )}
          </div>

          <footer className="style-panel-footer">
            <button
              type="button"
              className="style-btn style-btn-ghost"
              disabled={busy || !configDirty}
              onClick={() => {
                setConfigText(formatConfig(style.config));
                setConfigError(null);
              }}
              title="Discard edits and show the config currently on this chart"
            >
              <RotateCcw size={14} />
              Reset
            </button>
            <button
              type="button"
              className="style-btn style-btn-ghost"
              disabled={busy || !hasConfig}
              onClick={() => void applyConfig('')}
              title="Remove the config from this chart"
            >
              <Trash2 size={14} />
              Clear
            </button>
            <button
              type="button"
              className="style-btn style-btn-primary"
              disabled={busy || !configDirty}
              onClick={() => void applyConfig(configText)}
              title="Apply (Ctrl+Enter)"
            >
              {busy ? 'Applying…' : 'Apply'}
            </button>
          </footer>
        </>
      )}
    </aside>
  );
}
