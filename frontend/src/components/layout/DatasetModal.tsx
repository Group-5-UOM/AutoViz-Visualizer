import { useEffect, useState, useRef, type ChangeEvent, type DragEvent } from 'react';
import { Database, X, Trash2, Calendar, LayoutGrid, RotateCcw, Rows, Upload, Table } from 'lucide-react';
import { errorMessage } from '../../lib/api';
import { listDatasets, deleteDataset, previewDataset, type DatasetMetadata } from '../../lib/datasets';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import { ConfirmDialog } from './ConfirmDialog';
import './DatasetModal.css';
import { UPLOAD_ACCEPT, isAcceptedFile } from '../../lib/uploads';

interface DatasetModalProps {
  currentDatasetId?: string;
  onClose: () => void;
  onSelect: (dataset: DatasetMetadata) => void;
  onCsvSelected: (file: File) => Promise<void>;
  uploading?: boolean;
}

export function DatasetModal({ currentDatasetId, onClose, onSelect, onCsvSelected, uploading }: DatasetModalProps) {
  const [datasets, setDatasets] = useState<DatasetMetadata[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [previewData, setPreviewData] = useState<{ rows: Record<string, unknown>[], columns: string[] } | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  // Bumped by the retry button. A counter rather than a boolean so a second
  // attempt after a second failure still re-runs the effect.
  const [attempt, setAttempt] = useState(0);
  /** A failed action on the list — kept apart from `error`, which means the
   *  list itself could not load and replaces the whole panel. */
  const [actionError, setActionError] = useState<string | null>(null);
  /** The dataset a delete has been requested for, awaiting confirmation. */
  const [pendingDelete, setPendingDelete] = useState<DatasetMetadata | null>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  useFocusTrap(dialogRef, !pendingDelete);

  useEffect(() => {
    let mounted = true;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await listDatasets();
        if (mounted) {
          const sorted = res.datasets.sort(
            (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
          );
          setDatasets(sorted);
        }
      } catch (err) {
        // The server's own words: "Not signed in" and "Could not reach the
        // server" call for different things from the user.
        if (mounted) setError(errorMessage(err));
      } finally {
        if (mounted) setLoading(false);
      }
    }
    load();
    return () => {
      mounted = false;
    };
  }, [uploading, attempt]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  const handleOverlayClick = (e: React.MouseEvent) => {
    if (e.target === overlayRef.current) onClose();
  };

  const runDelete = async (id: string) => {
    setPendingDelete(null);
    setActionError(null);
    try {
      await deleteDataset(id);
      setDatasets((prev) => prev.filter((d) => d.dataset_id !== id));
      if (expandedId === id) {
        setExpandedId(null);
      }
    } catch (err) {
      // Was a `window.alert` reading "Failed to delete dataset." — which stops
      // the page, names no cause, and is gone the moment it is dismissed. The
      // delete button is still there, so re-clicking it is the retry.
      setActionError(`Could not delete that dataset. ${errorMessage(err)}`);
    }
  };

  const handleDatasetClick = async (dataset: DatasetMetadata) => {
    setExpandedId(dataset.dataset_id);
    setPreviewLoading(true);
    setPreviewData(null);
    setPreviewError(null);
    try {
      const res = await previewDataset(dataset.dataset_id, 10);
      if (res.rows && res.rows.length > 0) {
        const columns = Object.keys(res.rows[0]);
        setPreviewData({ rows: res.rows, columns });
      } else {
        setPreviewData({ rows: [], columns: [] });
      }
    } catch (err) {
      // Without this the pane fell back to its empty state, which says the
      // dataset has no rows — a claim about the data, made because a request
      // failed.
      setPreviewError(errorMessage(err));
    } finally {
      setPreviewLoading(false);
    }
  };

  const formatDate = (isoString: string) => {
    const date = new Date(isoString);
    return date.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  };

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      void onCsvSelected(file);
      e.target.value = '';
    }
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

  const selectedDataset = datasets.find(d => d.dataset_id === expandedId);
  const isSelectedCurrent = selectedDataset && selectedDataset.dataset_id === currentDatasetId;

  return (
    <div className="dataset-modal-overlay" ref={overlayRef} onClick={handleOverlayClick}>
      <div className="dataset-modal" role="dialog" aria-modal="true" ref={dialogRef}>
        <div className="dataset-modal-header">
          <h2 className="dataset-header-title">
            <Database size={18} />
            Your Uploaded Data
          </h2>
          <button className="modal-close-btn" onClick={onClose} aria-label="Close">
            <X size={20} />
          </button>
        </div>

        {actionError && (
          <div className="modal-action-error" role="alert">
            <span>{actionError}</span>
            <button type="button" onClick={() => setActionError(null)} aria-label="Dismiss">
              <X size={14} />
            </button>
          </div>
        )}

        <div className="dataset-modal-body">
          <div className="dataset-modal-sidebar">
            <div className="dataset-list-container">
              {loading ? (
                <div className="data-loading">
                  <div className="spinner" />
                  <span>Loading datasets...</span>
                </div>
              ) : error ? (
                <div className="data-loading" role="alert">
                  <span style={{ color: 'var(--danger, #ef4444)' }}>{error}</span>
                  <button
                    type="button"
                    className="panel-retry-btn"
                    onClick={() => setAttempt((n) => n + 1)}
                  >
                    <RotateCcw size={13} />
                    Try again
                  </button>
                </div>
              ) : datasets.length === 0 ? (
                <div className="data-empty">
                  <Database size={32} strokeWidth={1} />
                  <h3>No datasets found</h3>
                  <p>Upload a data file.</p>
                </div>
              ) : (
                <div className="dataset-list">
                  {datasets.map((dataset) => {
                    const isSelected = expandedId === dataset.dataset_id;
                    const isCurrent = dataset.dataset_id === currentDatasetId;
                    
                    return (
                      <div
                        key={dataset.dataset_id}
                        className={`dataset-item ${isSelected ? 'is-selected' : ''}`}
                        onClick={() => handleDatasetClick(dataset)}
                      >
                        <div className="dataset-item-info">
                          <div className="dataset-item-name" title={dataset.logical_name}>
                            {dataset.logical_name}
                            {isCurrent && <span className="current-badge">Active</span>}
                          </div>
                          <div className="dataset-item-meta">
                            <span title="Rows">
                              <Rows size={12} />
                              {dataset.row_count.toLocaleString()}
                            </span>
                            <span title="Columns">
                              <LayoutGrid size={12} />
                              {dataset.column_count.toLocaleString()}
                            </span>
                            <span title="Uploaded at">
                              <Calendar size={12} />
                              {formatDate(dataset.created_at)}
                            </span>
                          </div>
                        </div>
                        <div className="dataset-item-actions">
                          <button
                            className="btn-delete"
                            onClick={(e) => {
                              e.stopPropagation();
                              setPendingDelete(dataset);
                            }}
                            title="Delete dataset"
                            aria-label="Delete dataset"
                          >
                            <Trash2 size={16} />
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>

          <div 
            className={`dataset-modal-content ${isDragging ? 'is-dragging' : ''}`}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            {selectedDataset ? (
              <>
                <div className="dataset-preview-header">
                  <h3>Preview: {selectedDataset.logical_name}</h3>
                </div>
                <div className="dataset-preview-scroll">
                  {previewLoading ? (
                     <div className="data-loading" style={{ paddingTop: 80 }}>
                       <div className="spinner" style={{ width: 32, height: 32 }} />
                       <span>Loading preview...</span>
                     </div>
                  ) : previewError ? (
                    <div className="data-loading" style={{ paddingTop: 80 }} role="alert">
                      <span style={{ color: 'var(--danger, #ef4444)' }}>{previewError}</span>
                      <button
                        type="button"
                        className="panel-retry-btn"
                        onClick={() => void handleDatasetClick(selectedDataset)}
                      >
                        <RotateCcw size={13} />
                        Try again
                      </button>
                    </div>
                  ) : previewData ? (
                    <div className="dataset-preview-table-wrap">
                      <table className="dataset-preview-table">
                        <thead>
                          <tr>
                            {previewData.columns.map(col => (
                              <th key={col}>{col}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {previewData.rows.map((row, i) => (
                            <tr key={i}>
                              {previewData.columns.map(col => (
                                <td key={col} title={String(row[col] ?? '')}>
                                  {String(row[col] ?? '')}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <div className="data-loading">
                      <span style={{ color: 'var(--danger)' }}>Failed to load preview</span>
                    </div>
                  )}
                </div>
                {!isSelectedCurrent && (
                  <div className="dataset-preview-footer">
                    <button
                      className="btn-set-active"
                      onClick={() => onSelect(selectedDataset)}
                    >
                      Select to Dashboard
                    </button>
                  </div>
                )}
              </>
            ) : (
              <div className="dataset-preview-empty">
                <Table size={64} strokeWidth={1} />
                <h3>No dataset selected</h3>
                <p>Select a dataset from the list to preview its contents, or drop a new data file here.</p>
                <div style={{ marginTop: '16px' }}>
                  <label className="upload-label">
                    <Upload size={16} />
                    {uploading ? 'Uploading...' : 'Upload new CSV'}
                    <input
                      type="file"
                      accept={UPLOAD_ACCEPT}
                      className="upload-input"
                      onChange={handleFileChange}
                      disabled={uploading}
                    />
                  </label>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {pendingDelete && (
        <ConfirmDialog
          destructive
          title="Delete this dataset?"
          body={
            <>
              <p>
                <strong>{pendingDelete.logical_name}</strong> —{' '}
                {pendingDelete.row_count.toLocaleString()} rows ×{' '}
                {pendingDelete.column_count.toLocaleString()} columns.
              </p>
              <p>
                Every saved chart built from this dataset is deleted with it, and any
                dashboard holding one of those charts loses it. This cannot be undone.
              </p>
            </>
          }
          confirmLabel="Delete dataset"
          onCancel={() => setPendingDelete(null)}
          onConfirm={() => void runDelete(pendingDelete.dataset_id)}
        />
      )}
    </div>
  );
}
