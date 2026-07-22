import { ChartWidgetCard } from './ChartWidget';
import type { ChartWidget } from '../../types/dashboard';
import './DashboardCanvas.css';

interface DashboardCanvasProps {
  widgets: ChartWidget[];
  selectedWidgetId: string | null;
  onSelect: (id: string | null) => void;
  onUpdate: (id: string, patch: Partial<ChartWidget>) => void;
  onDelete: (id: string) => void;
}

export function DashboardCanvas({
  widgets,
  selectedWidgetId,
  onSelect,
  onUpdate,
  onDelete,
}: DashboardCanvasProps) {
  return (
    <main
      className="dashboard-canvas"
      onPointerDown={() => onSelect(null)}
      aria-label="Dashboard canvas"
    >
      <div className="canvas-grid" aria-hidden />

      {widgets.length === 0 && (
        <div className="canvas-empty">
          <div className="canvas-empty-card">
            <h2>Your dashboard canvas</h2>
            <p>
              Ask the AI chat to create a visualization. Charts will appear here
              so you can move, resize, and arrange them into a dashboard.
            </p>
          </div>
        </div>
      )}

      <div className="canvas-stage">
        {widgets.map((widget) => (
          <ChartWidgetCard
            key={widget.id}
            widget={widget}
            selected={selectedWidgetId === widget.id}
            onSelect={() => onSelect(widget.id)}
            onDelete={() => onDelete(widget.id)}
            onMove={(x, y) => onUpdate(widget.id, { x, y })}
            onResize={(width, height) => onUpdate(widget.id, { width, height })}
          />
        ))}
      </div>
    </main>
  );
}
