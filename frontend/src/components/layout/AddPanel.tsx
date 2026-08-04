import { useRef, type ChangeEvent } from 'react';
import { Database, FileSpreadsheet, Plus, Upload, X } from 'lucide-react';
import './ToolSidePanel.css';

interface DatasetInfo {
  fileName: string;
  rowCount: number;
  columnCount: number;
}

interface AddPanelProps {
  open: boolean;
  uploading?: boolean;
  uploadError?: string | null;
  dataset: DatasetInfo | null;
  onClose: () => void;
  onCsvSelected: (file: File) => void | Promise<void>;
  onBrowseDatasets: () => void;
}

export function AddPanel({
  open,
  uploading,
  uploadError,
  dataset,
  onClose,
  onCsvSelected,
  onBrowseDatasets,
}: AddPanelProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);

  if (!open) return null;

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    void onCsvSelected(file);
    e.target.value = '';
  };

  return (
    <section className="tool-panel" aria-label="Add CSV">
      <header className="tool-panel-header">
        <div className="tool-panel-header-title">
          <Plus size={16} />
          <span>Add</span>
        </div>
        <button type="button" className="tool-panel-close" onClick={onClose} aria-label="Close add panel">
          <X size={16} />
        </button>
      </header>

      <div className="tool-panel-body">
        <p className="tool-panel-copy">
          Upload a CSV to AutoViz. Once it is loaded, open Setup to pick a chart type and ask the bot to draw it.
        </p>

        <div className="tool-panel-section">
          <h3>CSV file</h3>
          <button
            type="button"
            className="tool-action-btn"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
          >
            <Upload size={16} />
            <span>
              {uploading ? 'Uploading…' : dataset ? 'Replace CSV file' : 'Upload CSV file'}
              <span className="tool-action-meta">Add a spreadsheet to the platform</span>
            </span>
          </button>
          <button type="button" className="tool-action-btn" onClick={onBrowseDatasets} disabled={uploading}>
            <Database size={16} />
            <span>
              Browse uploaded datasets
              <span className="tool-action-meta">Reuse a CSV already on the platform</span>
            </span>
          </button>
          {uploadError && (
            <p className="tool-panel-copy" role="alert" style={{ color: 'var(--danger, #b91c1c)' }}>
              {uploadError}
            </p>
          )}
        </div>

        <div className="tool-panel-section">
          <h3>Current dataset</h3>
          {dataset ? (
            <div className="tool-dataset-card">
              <FileSpreadsheet size={18} />
              <div>
                <strong>{dataset.fileName}</strong>
                <span>
                  {dataset.rowCount.toLocaleString()} rows · {dataset.columnCount} columns
                </span>
              </div>
            </div>
          ) : (
            <div className="tool-empty">No CSV loaded yet.</div>
          )}
        </div>

        <input
          ref={fileInputRef}
          type="file"
          accept=".csv,text/csv"
          className="tool-file-input"
          onChange={handleFileChange}
          disabled={uploading}
        />
      </div>
    </section>
  );
}
