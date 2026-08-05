import { useRef, type ChangeEvent } from 'react';
import { Plus, Upload, X } from 'lucide-react';
import './ToolSidePanel.css';

interface AddPanelProps {
  open: boolean;
  uploading?: boolean;
  uploadError?: string | null;
  onClose: () => void;
  onCsvSelected: (file: File) => void | Promise<void>;
}

export function AddPanel({
  open,
  uploading,
  uploadError,
  onClose,
  onCsvSelected,
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
    <section className="tool-panel" aria-label="Add dataset">
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
          Upload a new CSV dataset to start building charts on the canvas.
        </p>

        <div className="tool-panel-section">
          <h3>New dataset</h3>
          <button
            type="button"
            className="tool-action-btn"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
          >
            <Upload size={16} />
            <span>
              {uploading ? 'Uploading…' : 'Upload CSV'}
              <span className="tool-action-meta">Add a new dataset to AutoViz</span>
            </span>
          </button>
          {uploadError && (
            <p className="tool-panel-copy" role="alert" style={{ color: 'var(--danger, #b91c1c)' }}>
              {uploadError}
            </p>
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
