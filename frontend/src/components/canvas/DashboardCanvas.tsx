import { useEffect, useRef, useState, type ChangeEvent } from 'react';
import { FileSpreadsheet, Table, Upload } from 'lucide-react';
import { ChartWidgetCard } from './ChartWidget';
import { previewDataset } from '../../lib/datasets';
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
  /** Open the full spreadsheet / dataset editor view. */
  onOpenData?: () => void;
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
}: DashboardCanvasProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const showUploadPrompt = widgets.length === 0 && !dataset;
  const showDatasetPreview = widgets.length === 0 && Boolean(dataset);

  const [previewColumns, setPreviewColumns] = useState<string[]>([]);
  const [previewRows, setPreviewRows] = useState<Record<string, unknown>[]>([]);
  const [previewLoading, setPreviewLoading] = useState(false);

  useEffect(() => {
    if (!dataset || widgets.length > 0) {
      setPreviewColumns([]);
      setPreviewRows([]);
      return;
    }
    let cancelled = false;
    setPreviewLoading(true);
    void previewDataset(dataset.datasetId, 25)
      .then((res) => {
        if (cancelled) return;
        const cols = res.rows.length > 0 ? Object.keys(res.rows[0]) : [];
        setPreviewColumns(cols);
        setPreviewRows(res.rows);
      })
      .catch(() => {
        if (cancelled) return;
        setPreviewColumns([]);
        setPreviewRows([]);
      })
      .finally(() => {
        if (!cancelled) setPreviewLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [dataset?.datasetId, widgets.length]);

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

      {showDatasetPreview && dataset && (
        <div
          className="canvas-dataset-preview"
          onPointerDown={(e) => e.stopPropagation()}
        >
          <div className="canvas-dataset-preview-header">
            <div>
              <h2>{dataset.fileName}</h2>
              <p>
                {dataset.rowCount.toLocaleString()} rows × {dataset.columnCount} columns
                {previewLoading ? ' · loading preview…' : ''}
              </p>
            </div>
            <div className="canvas-dataset-preview-actions">
              <button
                type="button"
                className="canvas-upload-btn"
                onClick={onOpenData}
              >
                <Table size={16} />
                Open spreadsheet
              </button>
              <button
                type="button"
                className="canvas-upload-btn canvas-upload-btn--secondary"
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
              >
                <Upload size={16} />
                {uploading ? 'Uploading…' : 'Replace CSV'}
              </button>
            </div>
          </div>

          {uploadError && (
            <p className="canvas-upload-error" role="alert">
              {uploadError}
            </p>
          )}

          <div className="canvas-dataset-preview-table-wrap">
            {previewColumns.length > 0 ? (
              <table className="canvas-dataset-preview-table">
                <thead>
                  <tr>
                    {previewColumns.map((col) => (
                      <th key={col}>{col}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {previewRows.map((row, i) => (
                    <tr key={i}>
                      {previewColumns.map((col) => (
                        <td key={col}>
                          {row[col] === null || row[col] === undefined
                            ? '—'
                            : String(row[col])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              !previewLoading && (
                <p className="canvas-dataset-preview-empty">No preview rows available.</p>
              )
            )}
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,text/csv"
            className="canvas-file-input"
            onChange={handleFileChange}
            disabled={uploading}
          />
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
