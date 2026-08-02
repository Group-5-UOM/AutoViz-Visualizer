import { useRef, type ChangeEvent } from 'react';
import { FileSpreadsheet, Upload } from 'lucide-react';
import { ChartWidgetCard } from './ChartWidget';
import type { ChartWidget } from '../../types/dashboard';
import './DashboardCanvas.css';

interface DatasetInfo {
  datasetId: string;
  fileName: string;
  rowCount: number;
  columnCount: number;
}

interface DashboardCanvasProps {
  widgets: ChartWidget[];
  selectedWidgetId: string | null;
  dataset: DatasetInfo | null;
  uploading: boolean;
  uploadError: string | null;
  onSelect: (id: string | null) => void;
  onUpdate: (id: string, patch: Partial<ChartWidget>) => void;
  /** Restyle one chart in place. Resolves to an error message, or null on success. */
  onEditStyle: (id: string, request: string) => Promise<string | null>;
  /** Open the direct style controls for one chart. */
  onOpenStyle: (id: string) => void;
  /** Attach one chart to the next chat message. */
  onReference: (id: string) => void;
  referencedWidgetId: string | null;
  onDelete: (id: string) => void;
  onCsvSelected: (file: File) => void;
}

export function DashboardCanvas({
  widgets,
  selectedWidgetId,
  dataset,
  uploading,
  uploadError,
  onSelect,
  onUpdate,
  onEditStyle,
  onOpenStyle,
  onReference,
  referencedWidgetId,
  onDelete,
  onCsvSelected,
}: DashboardCanvasProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const showUploadPrompt = widgets.length === 0 && !dataset;

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    void onCsvSelected(file);
    e.target.value = '';
  };

  return (
    <main
      className="dashboard-canvas"
      onPointerDown={() => onSelect(null)}
      aria-label="Dashboard canvas"
    >
      <div className="canvas-grid" aria-hidden />

      {showUploadPrompt && (
        <div className="canvas-empty">
          <div className="canvas-empty-card">
            <div className="canvas-upload-icon" aria-hidden>
              <FileSpreadsheet size={28} strokeWidth={1.75} />
            </div>
            <h2>Add a CSV file</h2>
            <p>
              Upload a structured CSV dataset to start asking questions and
              building charts on this canvas.
            </p>
            <button
              type="button"
              className="canvas-upload-btn"
              onPointerDown={(e) => e.stopPropagation()}
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
            >
              <Upload size={16} />
              {uploading ? 'Uploading…' : 'Add CSV file'}
            </button>
            {uploadError && (
              <p className="canvas-upload-error" role="alert">
                {uploadError}
              </p>
            )}
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,text/csv"
              className="canvas-file-input"
              onChange={handleFileChange}
              disabled={uploading}
            />
          </div>
        </div>
      )}

      {widgets.length === 0 && dataset && (
        <div className="canvas-empty">
          <div className="canvas-empty-card">
            <div className="canvas-upload-icon is-ready" aria-hidden>
              <FileSpreadsheet size={28} strokeWidth={1.75} />
            </div>
            <h2>Dataset ready</h2>
            <p>
              <strong>{dataset.fileName}</strong> is loaded on the server
              ({dataset.rowCount.toLocaleString()} rows × {dataset.columnCount}{' '}
              cols). Ask the AI chat to create a visualization — charts will
              appear here.
            </p>
            <button
              type="button"
              className="canvas-upload-btn canvas-upload-btn--secondary"
              onPointerDown={(e) => e.stopPropagation()}
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
            >
              <Upload size={16} />
              {uploading ? 'Uploading…' : 'Replace CSV'}
            </button>
            {uploadError && (
              <p className="canvas-upload-error" role="alert">
                {uploadError}
              </p>
            )}
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,text/csv"
              className="canvas-file-input"
              onChange={handleFileChange}
              disabled={uploading}
            />
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
            onEditStyle={(request) => onEditStyle(widget.id, request)}
            onOpenStyle={() => onOpenStyle(widget.id)}
            onReference={() => onReference(widget.id)}
            referenced={referencedWidgetId === widget.id}
            onDelete={() => onDelete(widget.id)}
            onMove={(x, y) => onUpdate(widget.id, { x, y })}
            onResize={(width, height) => onUpdate(widget.id, { width, height })}
          />
        ))}
      </div>
    </main>
  );
}
