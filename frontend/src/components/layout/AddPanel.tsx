import { useRef, useState, type ChangeEvent, type DragEvent } from 'react';
import { Upload } from 'lucide-react';
import { useEscapeToClose } from '../../hooks/useEscapeToClose';
import './ToolSidePanel.css';
import { UPLOAD_ACCEPT, isAcceptedFile } from '../../lib/uploads';

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
  useEscapeToClose(onClose, open);

  if (!open) return null;

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    void onCsvSelected(file);
    e.target.value = '';
  };

  const [isDragging, setIsDragging] = useState(false);

  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    if (!uploading) setIsDragging(true);
  };

  const handleDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    if (uploading) return;
    
    const file = e.dataTransfer.files?.[0];
    if (!file) return;
    if (isAcceptedFile(file)) {
      void onCsvSelected(file);
    }
  };

  return (
    <section className="tool-panel" aria-label="Add dataset">
      <div className="tool-panel-body">
        <p className="tool-panel-copy">
          Upload a spreadsheet or data file to start building charts on the canvas.
        </p>

        <div 
          className={`tool-panel-section dropzone ${isDragging ? 'active' : ''}`}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          <h3>New dataset</h3>
          <button
            type="button"
            className="tool-action-btn"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
          >
            <Upload size={16} />
            <span>
              {uploading ? 'Uploading…' : 'Upload file'}
              <span className="tool-action-meta">
                {isDragging ? 'Drop file here' : 'Drag and drop or click to add'}
              </span>
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
          accept={UPLOAD_ACCEPT}
          className="tool-file-input"
          onChange={handleFileChange}
          disabled={uploading}
        />
      </div>
    </section>
  );
}
