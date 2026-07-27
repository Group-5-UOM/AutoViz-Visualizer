import { useEffect, useState, useRef } from 'react';
import { LayoutDashboard, X, Calendar, Layers } from 'lucide-react';
import { listDashboards, type DashboardResult } from '../../lib/dashboards';
import './DashboardsModal.css';

interface DashboardsModalProps {
  currentDashboardId?: string;
  onClose: () => void;
  onSelect: (dashboard: DashboardResult) => void;
}

export function DashboardsModal({ currentDashboardId, onClose, onSelect }: DashboardsModalProps) {
  const [dashboards, setDashboards] = useState<DashboardResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const overlayRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let mounted = true;
    async function load() {
      try {
        const res = await listDashboards();
        if (mounted) {
          const sorted = res.dashboards.sort(
            (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
          );
          setDashboards(sorted);
        }
      } catch (err) {
        if (mounted) setError('Failed to load dashboards.');
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

  const formatDate = (isoString: string) => {
    const date = new Date(isoString);
    return date.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  };

  return (
    <div className="dashboard-modal-overlay" ref={overlayRef} onClick={handleOverlayClick}>
      <div className="dashboard-modal" role="dialog" aria-modal="true" aria-labelledby="dashboard-modal-title">
        <div className="dashboard-modal-header">
          <h2 id="dashboard-modal-title">
            <LayoutDashboard size={18} />
            Your Saved Dashboards
          </h2>
          <button className="modal-close-btn" onClick={onClose} aria-label="Close">
            <X size={20} />
          </button>
        </div>

        <div className="dashboard-modal-body">
          {loading ? (
            <div className="dashboard-loading">
              <div className="spinner" />
              <span>Loading dashboards...</span>
            </div>
          ) : error ? (
            <div className="dashboard-loading">
              <span style={{ color: 'var(--danger, #ef4444)' }}>{error}</span>
            </div>
          ) : dashboards.length === 0 ? (
            <div className="dashboard-empty">
              <LayoutDashboard size={48} strokeWidth={1} />
              <h3>No dashboards found</h3>
              <p>Save a dashboard to see it here.</p>
            </div>
          ) : (
            <div className="dashboard-list">
              {dashboards.map((dashboard) => {
                const isCurrent = dashboard.id === currentDashboardId;
                return (
                  <div
                    key={dashboard.id}
                    className={`dashboard-item ${isCurrent ? 'is-current' : ''}`}
                    onClick={() => { if (!isCurrent) onSelect(dashboard); }}
                    style={{ cursor: isCurrent ? 'default' : 'pointer' }}
                  >
                    <div className="dashboard-item-info">
                      <div className="dashboard-item-name" title={dashboard.name}>
                        {dashboard.name}
                        {isCurrent && <span className="current-badge">Current</span>}
                      </div>
                      <div className="dashboard-item-meta">
                        <span title="Widgets">
                          <Layers size={14} />
                          {dashboard.widgets.length} charts
                        </span>
                        <span title="Created at">
                          <Calendar size={14} />
                          {formatDate(dashboard.created_at)}
                        </span>
                      </div>
                    </div>
                    <div className="dashboard-item-actions">
                      {!isCurrent && (
                        <button
                          className="btn-load"
                          onClick={() => onSelect(dashboard)}
                          title="Load this dashboard"
                        >
                          Load
                        </button>
                      )}
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
