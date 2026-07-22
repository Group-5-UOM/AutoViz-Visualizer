import { useEffect, useRef, type PointerEvent as ReactPointerEvent } from 'react';
import embed from 'vega-embed';
import { Trash2 } from 'lucide-react';
import type { ChartWidget } from '../../types/dashboard';
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
    const run = async () => {
      try {
        await embed(el, widget.vegaLiteSpec as never, {
          actions: false,
          renderer: 'svg',
          tooltip: true,
        });
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
      el.innerHTML = '';
    };
  }, [widget.vegaLiteSpec, widget.width, widget.height]);

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
        <button
          type="button"
          className="chart-delete-btn"
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
      </header>

      <div className="chart-widget-body" ref={chartRef} />

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
