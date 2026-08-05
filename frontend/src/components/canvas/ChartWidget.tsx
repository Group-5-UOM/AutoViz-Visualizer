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
}: ChartWidgetCardProps) {
  const chartRef = useRef<HTMLDivElement>(null);
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
      view?.finalize();
      el.innerHTML = '';
    };
  }, [widget.vegaLiteSpec]);

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
          // Never start a drag from the action buttons — that ate clicks before.
          if ((e.target as HTMLElement).closest('.chart-widget-actions')) return;
          startDrag(e, 'move');
        }}
      >
        <h3 title={widget.title}>{widget.title}</h3>
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
      </header>

      <div className="chart-widget-body" ref={chartRef} />

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

      <div
        className="chart-resize-handle"
        onPointerDown={(e) => startDrag(e, 'resize')}
        aria-hidden
      />
    </article>
  );
}
