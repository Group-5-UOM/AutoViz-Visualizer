import { useEffect, useState, useRef } from 'react';
import { Database, X, Trash2, Calendar, LayoutGrid, Rows } from 'lucide-react';
import { listDatasets, deleteDataset, type DatasetMetadata } from '../../lib/datasets';
import './DatasetModal.css';

interface DatasetModalProps {
  currentDatasetId?: string;
  onClose: () => void;
  onSelect: (dataset: DatasetMetadata) => void;
}

export function DatasetModal({ currentDatasetId, onClose, onSelect }: DatasetModalProps) {
  const [datasets, setDatasets] = useState<DatasetMetadata[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const overlayRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let mounted = true;
    async function load() {
      try {
        const res = await listDatasets();
        if (mounted) {
          // Sort by newest first based on created_at
          const sorted = res.datasets.sort(
            (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
          );
          setDatasets(sorted);
        }
      } catch (err) {
        if (mounted) setError('Failed to load datasets.');
      } finally {
        if (mounted) setLoading(false);
      }
    }
    load();
    return () => {
      mounted = false;
    };
  }, []);

  // Close on escape key
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

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation(); // prevent select
    if (!confirm('Are you sure you want to delete this dataset? This will also remove associated charts.')) {
      return;
    }
    try {
      await deleteDataset(id);
      setDatasets((prev) => prev.filter((d) => d.dataset_id !== id));
      if (id === currentDatasetId) {
        // If they delete the current dataset, we shouldn't necessarily force a reset here,
        // but they might see errors if they try to use it. Usually they load a new one anyway.
      }
    } catch (err) {
      alert('Failed to delete dataset.');
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

  return (
    <div className="dataset-modal-overlay" ref={overlayRef} onClick={handleOverlayClick}>
      <div className="dataset-modal" role="dialog" aria-modal="true" aria-labelledby="dataset-modal-title">
        <div className="dataset-modal-header">
          <h2 id="dataset-modal-title">
            <Database size={18} />
            Your Datasets
          </h2>
          <button className="modal-close-btn" onClick={onClose} aria-label="Close">
            <X size={20} />
          </button>
        </div>

        <div className="dataset-modal-body">
          {loading ? (
            <div className="dataset-loading">
              <div className="spinner" />
              <span>Loading datasets...</span>
            </div>
          ) : error ? (
            <div className="dataset-loading">
              <span style={{ color: 'var(--danger, #ef4444)' }}>{error}</span>
            </div>
          ) : datasets.length === 0 ? (
            <div className="dataset-empty">
              <Database size={48} strokeWidth={1} />
              <h3>No datasets found</h3>
              <p>Upload a CSV file to get started.</p>
            </div>
          ) : (
            <div className="dataset-list">
              {datasets.map((dataset) => {
                const isCurrent = dataset.dataset_id === currentDatasetId;
                return (
                  <div
                    key={dataset.dataset_id}
                    className={`dataset-item ${isCurrent ? 'is-current' : ''}`}
                  >
                    <div className="dataset-item-info">
                      <div className="dataset-item-name" title={dataset.logical_name}>
                        {dataset.logical_name}
                        {isCurrent && <span className="current-badge">Current</span>}
                      </div>
                      <div className="dataset-item-meta">
                        <span title="Rows">
                          <Rows size={14} />
                          {dataset.row_count.toLocaleString()}
                        </span>
                        <span title="Columns">
                          <LayoutGrid size={14} />
                          {dataset.column_count.toLocaleString()}
                        </span>
                        <span title="Uploaded at">
                          <Calendar size={14} />
                          {formatDate(dataset.created_at)}
                        </span>
                      </div>
                    </div>
                    <div className="dataset-item-actions">
                      {!isCurrent && (
                        <button
                          className="btn-load"
                          onClick={() => onSelect(dataset)}
                          title="Load this dataset"
                        >
                          Load
                        </button>
                      )}
                      <button
                        className="btn-delete"
                        onClick={(e) => handleDelete(e, dataset.dataset_id)}
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
    </div>
  );
}
