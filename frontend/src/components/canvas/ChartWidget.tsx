import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import embed from 'vega-embed';
import { BarChart3, Table2, Trash2 } from 'lucide-react';
import type { ChartWidget } from '../../types/dashboard';
import { specRows } from '../../lib/specData';
import { DataTable } from './DataTable';
import './ChartWidget.css';

interface ChartWidgetCardProps {
  widget: ChartWidget;
  selected: boolean;
  onSelect: () => void;
  onDelete: () => void;
  onMove: (x: number, y: number) => void;
  onResize: (width: number, height: number) => void;
}

export function ChartWidgetCard({
  widget,
  selected,
  onSelect,
  onDelete,
  onMove,
  onResize,
}: ChartWidgetCardProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const [showTable, setShowTable] = useState(false);
  const rows = useMemo(() => specRows(widget.vegaLiteSpec), [widget.vegaLiteSpec]);
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
          actions: false,
          renderer: 'svg',
          tooltip: true,
        });
        if (cancelled) {
          result.finalize();
          return;
        }
        view = result;
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
          <DataTable rows={rows} caption={`Data for ${widget.title}`} />
        </div>
      ) : (
        <div className="chart-widget-body" ref={chartRef} />
      )}

      {selected && (
        <p className="chart-explanation">{widget.explanation}</p>
      )}

      <div
        className="chart-resize-handle"
        onPointerDown={(e) => startDrag(e, 'resize')}
        aria-hidden
      />
    </article>
  );
}
