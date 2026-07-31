import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type PointerEvent as ReactPointerEvent,
} from 'react';
import embed from 'vega-embed';
import { AtSign, BarChart3, Palette, Table2, Trash2, Wand2 } from 'lucide-react';
import type { ChartWidget } from '../../types/dashboard';
import {
  BRUSH_SIGNAL,
  hasBrush,
  rowsInBrush,
  specRows,
  type BrushExtent,
} from '../../lib/specData';
import { DataTable } from './DataTable';
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
  const [showTable, setShowTable] = useState(false);
  const [brush, setBrush] = useState<BrushExtent | null>(null);
  // Editing lives on the card rather than in the chat so there is never a
  // question of which chart an instruction is about.
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState('');
  const [editBusy, setEditBusy] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const rows = useMemo(() => specRows(widget.vegaLiteSpec), [widget.vegaLiteSpec]);
  // Brushing the chart narrows its table view to the selected rows.
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

  // The spec sizes itself from the container, so vega-embed's ResizeObserver
  // handles resizing — re-embedding on every drag frame would throw away the
  // view's interaction state (legend filter, zoom) mid-gesture.
  useEffect(() => {
    const el = chartRef.current;
    // Nothing to embed into while the table is showing; re-runs when it closes.
    if (!el || showTable) return;

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
        // Only brushable charts carry this signal; asking for it elsewhere throws.
        try {
          result.view.addSignalListener(BRUSH_SIGNAL, (_name, value) => {
            setBrush(value as BrushExtent);
          });
        } catch {
          /* chart has no brush — nothing to listen to */
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
  }, [widget.vegaLiteSpec, showTable]);

  useEffect(() => {
    const onPointerMove = (e: PointerEvent) => {
      const drag = dragRef.current;
      if (!drag) return;
      const dx = e.clientX - drag.startX;
      const dy = e.clientY - drag.startY;

      if (drag.mode === 'move') {
        onMove(
          Math.max(0, drag.originX + dx),
          Math.max(0, drag.originY + dy),
        );
      } else {
        onResize(
          Math.max(280, drag.originW + dx),
          Math.max(200, drag.originH + dy),
        );
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
      // The chart was left as it was, so the box keeps what was typed for
      // editing rather than making the user start again.
      setEditError(failure);
      return;
    }
    setEditText('');
  };

  const startDrag = (
    e: ReactPointerEvent,
    mode: 'move' | 'resize',
  ) => {
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
        onPointerDown={(e) => startDrag(e, 'move')}
      >
        <h3>{widget.title}</h3>
        <div className="chart-widget-actions">
          {rows && (
            <button
              type="button"
              className="chart-header-btn"
              title={showTable ? 'Show chart' : 'Show data table'}
              aria-label={showTable ? 'Show chart' : 'Show data table'}
              aria-pressed={showTable}
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => {
                e.stopPropagation();
                setShowTable((on) => !on);
              }}
            >
              {showTable ? <BarChart3 size={14} /> : <Table2 size={14} />}
            </button>
          )}
          {/* Only a chart this conversation produced can be referenced: one
              restored from a saved dashboard has no thread behind it to edit. */}
          {widget.agentChartId && (
            <button
              type="button"
              className="chart-header-btn"
              title={referenced ? 'Attached to the chat' : 'Ask the chat about this chart'}
              aria-label={referenced ? 'Attached to the chat' : 'Ask the chat about this chart'}
              aria-pressed={referenced}
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => {
                e.stopPropagation();
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
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => {
              e.stopPropagation();
              onSelect();
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
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => {
              e.stopPropagation();
              onSelect();
              setEditing((on) => !on);
              setEditError(null);
            }}
          >
            <Wand2 size={14} />
          </button>
          <button
            type="button"
            className="chart-header-btn is-danger"
            title="Delete chart"
            aria-label="Delete chart"
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
          >
            <Trash2 size={14} />
          </button>
        </div>
      </header>

      {showTable && rows ? (
        <div className="chart-widget-body is-table">
          <DataTable rows={tableRows} caption={`Data for ${widget.title}`} />
        </div>
      ) : (
        <div className="chart-widget-body" ref={chartRef} />
      )}

      {hasBrush(brush) && rows && (
        <p className="chart-brush-status">
          {tableRows.length.toLocaleString()} of {rows.length.toLocaleString()} rows
          selected{showTable ? '' : ' — open the table to read them'}
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
            // Escape closes without touching the chart; the canvas would
            // otherwise deselect the card out from under the input.
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
        selected && <p className="chart-explanation">{widget.explanation}</p>
      )}

      <div
        className="chart-resize-handle"
        onPointerDown={(e) => startDrag(e, 'resize')}
        aria-hidden
      />
    </article>
  );
}
