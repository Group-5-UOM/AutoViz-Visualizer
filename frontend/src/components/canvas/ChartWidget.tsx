import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type PointerEvent as ReactPointerEvent,
} from 'react';
import embed from 'vega-embed';
import {
  AtSign,
  Palette,
  Trash2,
  WandSparkles,
} from 'lucide-react';
import type { ChartWidget } from '../../types/dashboard';
import {
  BRUSH_SIGNAL,
  hasBrush,
  rowsInBrush,
  specRows,
  type BrushExtent,
} from '../../lib/specData';
import './ChartWidget.css';

/**
 * The part of a Vega view this card drives. Structural rather than imported so
 * the component keeps its one dependency on `vega-embed` and does not grow a
 * direct one on `vega` for a type.
 */
interface ChartView {
  width: (px: number) => unknown;
  height: (px: number) => unknown;
  resize: () => { runAsync: () => Promise<unknown> };
}

interface ChartWidgetCardProps {
  widget: ChartWidget;
  selected: boolean;
  onSelect: () => void;
  /** Restyle this chart. Resolves to an error message, or null on success. */
  onEditStyle: (request: string) => Promise<string | null>;
  /** Open the direct controls for the same styling. */
  onOpenStyle: () => void;
  /** Attach this chart to the next chat message. */
  onReference: () => void;
  /** This chart is the one currently attached to the composer. */
  referenced: boolean;
  onDelete: () => void;
  onMove: (x: number, y: number) => void;
  onResize: (width: number, height: number) => void;
  readOnly?: boolean;
}

export function ChartWidgetCard({
  widget,
  selected,
  onSelect,
  onEditStyle,
  onOpenStyle,
  onReference,
  referenced,
  onDelete,
  onMove,
  onResize,
  readOnly,
}: ChartWidgetCardProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  // Held so the resize observer below can drive the live view. Not state: it
  // changes on re-embed, which already re-renders, and nothing reads it during
  // render.
  const viewRef = useRef<ChartView | null>(null);
  const [brush, setBrush] = useState<BrushExtent | null>(null);
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState('');
  const [editBusy, setEditBusy] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const rows = useMemo(() => specRows(widget.vegaLiteSpec), [widget.vegaLiteSpec]);
  const tableRows = useMemo(() => rowsInBrush(rows ?? [], brush), [rows, brush]);
  const dragRef = useRef<{
    mode: 'move' | 'resize';
    startX: number;
    startY: number;
    originX: number;
    originY: number;
    originW: number;
    originH: number;
  } | null>(null);

  useEffect(() => {
    const el = chartRef.current;
    if (!el) return;

    let cancelled = false;
    let view: { finalize: () => void } | null = null;

    const run = async () => {
      try {
        const result = await embed(el, widget.vegaLiteSpec as never, {
          actions: { export: true, source: false, compiled: false, editor: false },
          renderer: 'svg',
          tooltip: true,
        });
        if (cancelled) {
          result.finalize();
          return;
        }
        view = result;
        viewRef.current = result.view as unknown as ChartView;
        try {
          result.view.addSignalListener(BRUSH_SIGNAL, (_name, value) => {
            setBrush(value as BrushExtent);
          });
        } catch {
          /* chart has no brush */
        }
      } catch (err) {
        if (!cancelled) {
          el.innerHTML = `<p class="chart-error">Could not render chart</p>`;
          console.error(err);
        }
      }
    };
    void run();

    return () => {
      cancelled = true;
      viewRef.current = null;
      view?.finalize();
      el.innerHTML = '';
    };
  }, [widget.vegaLiteSpec]);

  /**
   * Keep the chart the size of its card.
   *
   * The spec asks for `width`/`height: "container"`, but Vega-Lite compiles that
   * to a signal that measures the container once and re-measures on one event
   * only — `window:resize`. Dragging the resize handle changes this card's box
   * and fires nothing of the sort, so without this the card grows and the chart
   * inside it does not. vega-embed installs no observer of its own.
   *
   * The element is created on the first render and never replaced, so this
   * mounts once and survives every re-embed.
   */
  useEffect(() => {
    const el = chartRef.current;
    if (!el) return;

    let frame = 0;
    const observer = new ResizeObserver(() => {
      // A drag reports on every pointer frame, and a relayout is not free on a
      // chart with many marks — coalesce to one per painted frame.
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        const view = viewRef.current;
        if (!view) return;
        // What `containerSize()` reads: vega-embed initialises the view against
        // the wrapper it inserts, not the element it was handed. Falling back to
        // `el` is still right — that is the container when there is no wrapper.
        const box = el.querySelector<HTMLElement>('.chart-wrapper') ?? el;
        // Mid-teardown, or a hidden card: a zero-size view is not worth drawing
        // and would leave the chart collapsed once it came back.
        if (!box.clientWidth || !box.clientHeight) return;
        view.width(box.clientWidth);
        view.height(box.clientHeight);
        void view.resize().runAsync();
      });
    });

    observer.observe(el);
    return () => {
      observer.disconnect();
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);

  useEffect(() => {
    const onPointerMove = (e: PointerEvent) => {
      const drag = dragRef.current;
      if (!drag) return;
      const dx = e.clientX - drag.startX;
      const dy = e.clientY - drag.startY;

      if (drag.mode === 'move') {
        onMove(Math.max(0, drag.originX + dx), Math.max(0, drag.originY + dy));
      } else {
        onResize(Math.max(280, drag.originW + dx), Math.max(200, drag.originH + dy));
      }
    };

    const onPointerUp = () => {
      dragRef.current = null;
    };

    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
    return () => {
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
    };
  }, [onMove, onResize]);

  const submitEdit = async (e: FormEvent) => {
    e.preventDefault();
    const request = editText.trim();
    if (!request || editBusy) return;
    setEditBusy(true);
    setEditError(null);
    const failure = await onEditStyle(request);
    setEditBusy(false);
    if (failure) {
      setEditError(failure);
      return;
    }
    setEditText('');
    setEditing(false);
  };

  const startDrag = (e: ReactPointerEvent, mode: 'move' | 'resize') => {
    e.stopPropagation();
    e.preventDefault();
    onSelect();
    dragRef.current = {
      mode,
      startX: e.clientX,
      startY: e.clientY,
      originX: widget.x,
      originY: widget.y,
      originW: widget.width,
      originH: widget.height,
    };
  };

  const stopActionPointer = (e: ReactPointerEvent | React.MouseEvent) => {
    e.stopPropagation();
  };

  return (
    <article
      className={`chart-widget ${selected ? 'is-selected' : ''}`}
      style={{
        left: widget.x,
        top: widget.y,
        width: widget.width,
        height: widget.height,
      }}
      onPointerDown={onSelect}
    >
      <header
        className="chart-widget-header"
        onPointerDown={(e) => {
          if (readOnly) return;
          // Never start a drag from the action buttons — that ate clicks before.
          if ((e.target as HTMLElement).closest('.chart-widget-actions')) return;
          startDrag(e, 'move');
        }}
      >
        <h3 title={widget.title}>{widget.title}</h3>
        {!readOnly && (
          <div className="chart-widget-actions" onPointerDown={stopActionPointer}>
            {widget.agentChartId && (
              <button
                type="button"
                className="chart-header-btn"
                title={referenced ? 'Attached to the chat' : 'Ask the chat about this chart'}
                aria-label={referenced ? 'Attached to the chat' : 'Ask the chat about this chart'}
                aria-pressed={referenced}
                onClick={(e) => {
                  e.stopPropagation();
                  onSelect();
                  onReference();
                }}
              >
                <AtSign size={14} />
              </button>
            )}

            <button
              type="button"
              className="chart-header-btn"
              title="Style options"
              aria-label="Style options"
              onClick={(e) => {
                e.stopPropagation();
                onSelect();
                setEditing(false);
                onOpenStyle();
              }}
            >
              <Palette size={14} />
            </button>

            <button
              type="button"
              className="chart-header-btn"
              title="Change how this chart looks"
              aria-label="Change how this chart looks"
              aria-pressed={editing}
              onClick={(e) => {
                e.stopPropagation();
                onSelect();
                setEditing((on) => !on);
                setEditError(null);
              }}
            >
              <WandSparkles size={14} />
            </button>

            <button
              type="button"
              className="chart-header-btn is-danger"
              title="Delete chart"
              aria-label="Delete chart"
              onClick={(e) => {
                e.stopPropagation();
                onDelete();
              }}
            >
              <Trash2 size={14} />
            </button>
          </div>
        )}
      </header>

      <div
        className={`chart-widget-body ${editing ? 'is-editing' : ''}`}
        ref={chartRef}
      />

      {hasBrush(brush) && rows && (
        <p className="chart-brush-status">
          {tableRows.length.toLocaleString()} of {rows.length.toLocaleString()} rows
          selected
        </p>
      )}

      {editing ? (
        <form
          className="chart-edit-bar"
          onSubmit={submitEdit}
          onPointerDown={(e) => e.stopPropagation()}
        >
          <input
            type="text"
            value={editText}
            autoFocus
            disabled={editBusy}
            placeholder="Make the bars orange, drop the legend…"
            aria-label={`Change how "${widget.title}" looks`}
            onChange={(e) => setEditText(e.target.value)}
            onKeyDown={(e) => {
              e.stopPropagation();
              if (e.key === 'Escape') setEditing(false);
            }}
          />
          <button type="submit" disabled={editBusy || !editText.trim()}>
            {editBusy ? 'Applying…' : 'Apply'}
          </button>
          {editError && (
            <p className="chart-edit-error" role="alert">
              {editError}
            </p>
          )}
        </form>
      ) : (
        selected && widget.explanation && (
          <p className="chart-explanation">{widget.explanation}</p>
        )
      )}

      {!readOnly && (
        <div
          className="chart-resize-handle"
          onPointerDown={(e) => startDrag(e, 'resize')}
          aria-hidden
        />
      )}
    </article>
  );
}
