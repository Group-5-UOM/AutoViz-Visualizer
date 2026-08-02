import { useEffect, useState } from 'react';
import { Palette, X } from 'lucide-react';
import type { ChartStyle, ChartWidget } from '../../types/dashboard';
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

interface StylePanelProps {
  widget: ChartWidget;
  busy: boolean;
  onApply: (style: ChartStyle) => void;
  onClose: () => void;
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

export function StylePanel({ widget, busy, onApply, onClose }: StylePanelProps) {
  const style = widget.style ?? {};
  const series = specSeries(widget.vegaLiteSpec);

  // Text is edited locally and committed on blur or Enter: firing a request per
  // keystroke would be one round trip and one autosave per character typed.
  const [titles, setTitles] = useState({
    title: style.title ?? '',
    x_title: style.x_title ?? '',
    y_title: style.y_title ?? '',
  });

  useEffect(() => {
    setTitles({
      title: widget.style?.title ?? '',
      x_title: widget.style?.x_title ?? '',
      y_title: widget.style?.y_title ?? '',
    });
  }, [widget.id, widget.style]);

  // Always the whole block: the backend treats it as the widget's styling state,
  // not a diff, so an omitted field would read as a revert.
  const patch = (change: ChartStyle) => onApply({ ...style, ...change });

  const commitText = (key: 'title' | 'x_title' | 'y_title') => {
    const next = titles[key].trim();
    if (next === (style[key] ?? '')) return;
    patch({ [key]: next || null } as ChartStyle);
  };

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

  return (
    <section
      className="style-panel"
      aria-label={`Style options for ${widget.title}`}
      // The canvas deselects on pointer-down, which would close this panel the
      // moment anyone reached for a control in it.
      onPointerDown={(e) => e.stopPropagation()}
    >
      <header className="style-panel-header">
        <div className="style-panel-title">
          <Palette size={16} />
          <span>Chart style</span>
        </div>
        <button type="button" className="style-close-btn" aria-label="Close style options" onClick={onClose}>
          <X size={16} />
        </button>
      </header>

      <div className="style-panel-body">
        <p className="style-panel-subject" title={widget.title}>
          {widget.title}
        </p>

        {textField('title', 'Title')}
        {textField('x_title', 'X-axis label')}
        {textField('y_title', 'Y-axis label')}

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
            label="Colour"
            value={style.mark_color ?? undefined}
            onChange={(hex) => patch({ mark_color: hex })}
          />
        )}
      </div>
    </section>
  );
}
