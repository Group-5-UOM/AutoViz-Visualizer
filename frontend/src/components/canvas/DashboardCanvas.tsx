import { useRef, useState, type ChangeEvent, type DragEvent } from 'react';
import { FileSpreadsheet, Table, Upload } from 'lucide-react';
import { ChartWidgetCard } from './ChartWidget';
import type { ChartWidget } from '../../types/dashboard';
import './DashboardCanvas.css';
import { ACCEPTED_LABEL, UPLOAD_ACCEPT, isAcceptedFile } from '../../lib/uploads';

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
  /** Open the spreadsheet view (Data tab). */
  onOpenData?: () => void;
  readOnly?: boolean;
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
  onOpenData,
  readOnly,
}: DashboardCanvasProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const showUploadPrompt = widgets.length === 0 && !dataset;
  const showReadyHint = widgets.length === 0 && Boolean(dataset);

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    void onCsvSelected(file);
    e.target.value = '';
  };

  const [isDragging, setIsDragging] = useState(false);

  const handleDragOver = (e: DragEvent<HTMLElement>) => {
    e.preventDefault();
    if (!uploading && showUploadPrompt) setIsDragging(true);
  };

  const handleDragLeave = (e: DragEvent<HTMLElement>) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: DragEvent<HTMLElement>) => {
    e.preventDefault();
    setIsDragging(false);
    if (uploading || !showUploadPrompt) return;
    
    const file = e.dataTransfer.files?.[0];
    if (!file) return;
    if (isAcceptedFile(file)) {
      void onCsvSelected(file);
    }
  };

  return (
    <main
      className={`dashboard-canvas ${isDragging ? 'is-dragging' : ''} ${readOnly ? 'is-readonly' : ''}`}
      onPointerDown={() => !readOnly && onSelect(null)}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      aria-label="Dashboard canvas"
    >
      <div className="canvas-grid" aria-hidden />

      {showUploadPrompt && (
        <div className="canvas-empty">
          <div className="canvas-empty-card">
            <div className="canvas-upload-icon" aria-hidden>
              <FileSpreadsheet size={28} strokeWidth={1.75} />
            </div>
            <h2>Add a data file</h2>
            <p>
              Upload a spreadsheet or data file to start asking questions and
              building charts on this canvas, or drop a file here.
            </p>
            <p className="canvas-empty-formats">{ACCEPTED_LABEL}</p>
            <button
              type="button"
              className="canvas-upload-btn"
              onPointerDown={(e) => e.stopPropagation()}
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
            >
              <Upload size={16} />
              {uploading ? 'Uploading…' : 'Add data file'}
            </button>
            {uploadError && (
              <p className="canvas-upload-error" role="alert">
                {uploadError}
              </p>
            )}
            <input
              ref={fileInputRef}
              type="file"
              accept={UPLOAD_ACCEPT}
              className="canvas-file-input"
              onChange={handleFileChange}
              disabled={uploading}
            />
          </div>
        </div>
      )}

      {showReadyHint && dataset && (
        <div className="canvas-empty">
          <div className="canvas-empty-card">
            <div className="canvas-upload-icon" aria-hidden>
              <FileSpreadsheet size={28} strokeWidth={1.75} />
            </div>
            <h2>{dataset.fileName}</h2>
            <p>
              {dataset.rowCount.toLocaleString()} rows ×{' '}
              {dataset.columnCount} columns. Use Setup or AI Chat to build
              charts, or open Data to view the spreadsheet.
            </p>
            <div className="canvas-dataset-preview-actions">
              {onOpenData && (
                <button
                  type="button"
                  className="canvas-upload-btn"
                  onPointerDown={(e) => e.stopPropagation()}
                  onClick={onOpenData}
                >
                  <Table size={16} />
                  Open Data
                </button>
              )}
              <button
                type="button"
                className="canvas-upload-btn canvas-upload-btn--secondary"
                onPointerDown={(e) => e.stopPropagation()}
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
              >
                <Upload size={16} />
                {uploading ? 'Uploading…' : 'Replace file'}
              </button>
            </div>
            {uploadError && (
              <p className="canvas-upload-error" role="alert">
                {uploadError}
              </p>
            )}
            <input
              ref={fileInputRef}
              type="file"
              accept={UPLOAD_ACCEPT}
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
            readOnly={readOnly}
            selected={selectedWidgetId === widget.id}
            onSelect={() => !readOnly && onSelect(widget.id)}
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
