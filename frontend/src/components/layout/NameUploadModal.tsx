import { useEffect, useRef, useState } from 'react';
import { FileSpreadsheet, X } from 'lucide-react';
import './SaveDashboardModal.css';

interface NameUploadModalProps {
  /** Original file the user picked (used for size hint / default name). */
  file: File;
  onCancel: () => void;
  onConfirm: (displayName: string) => void;
}

function stemFromFilename(name: string): string {
  return name.replace(/\.[^./\\]+$/, '').trim();
}

export function NameUploadModal({ file, onCancel, onConfirm }: NameUploadModalProps) {
  const [name, setName] = useState(stemFromFilename(file.name) || 'dataset');
  const overlayRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const trimmed = name.trim();

  useEffect(() => {
    inputRef.current?.select();
  }, []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onCancel]);

  const handleOverlayClick = (e: React.MouseEvent) => {
    if (e.target === overlayRef.current) onCancel();
  };

  const submit = () => {
    if (trimmed) onConfirm(trimmed);
  };

  return (
    <div className="dashboard-modal-overlay" ref={overlayRef} onClick={handleOverlayClick}>
      <div
        className="dashboard-modal save-dashboard-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="name-upload-title"
      >
        <div className="dashboard-modal-header">
          <h2 id="name-upload-title">
            <FileSpreadsheet size={18} />
            Name this dataset
          </h2>
          <button className="modal-close-btn" onClick={onCancel} aria-label="Close">
            <X size={20} />
          </button>
        </div>

        <div className="dashboard-modal-body">
          <label className="save-dashboard-label" htmlFor="name-upload-input">
            Dataset name
          </label>
          <input
            id="name-upload-input"
            ref={inputRef}
            className="save-dashboard-input"
            value={name}
            maxLength={120}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') submit();
            }}
            placeholder="e.g. Sales Q1"
          />
          <p className="save-dashboard-hint">
            This name is saved with the file and shown as the board title
            (AutoViz AI / {trimmed || '…'}).
          </p>
        </div>

        <div className="dashboard-modal-footer save-dashboard-footer">
          <button type="button" className="btn-cancel" onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className="btn-load" onClick={submit} disabled={!trimmed}>
            Upload
          </button>
        </div>
      </div>
    </div>
  );
}

/** Build the File that will be uploaded / stored under this display name. */
export function namedCsvFile(source: File, displayName: string): File {
  const stem = displayName.trim().replace(/\.csv$/i, '');
  const filename = `${stem || 'dataset'}.csv`;
  return new File([source], filename, {
    type: source.type || 'text/csv',
    lastModified: source.lastModified,
  });
}
