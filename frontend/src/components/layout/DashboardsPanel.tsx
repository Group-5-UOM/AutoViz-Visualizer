import { useEffect, useState } from 'react';
import { LayoutDashboard, X, Calendar, Layers } from 'lucide-react';
import { listDashboards, type DashboardResult } from '../../lib/dashboards';
import './DashboardsPanel.css';

interface DashboardsPanelProps {
  open: boolean;
  currentDashboardId?: string;
  onClose: () => void;
  onSelect: (dashboard: DashboardResult) => void;
}

export function DashboardsPanel({ open, currentDashboardId, onClose, onSelect }: DashboardsPanelProps) {
  const [dashboards, setDashboards] = useState<DashboardResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
    if (!open) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  const formatDate = (isoString: string) => {
    const date = new Date(isoString);
    return date.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  };

  return (
    <section className="dashboards-panel" aria-label="Saved Dashboards">
      <header className="dashboards-header">
        <div className="dashboards-header-title">
          <LayoutDashboard size={16} />
          <span>Dashboards</span>
        </div>
        <button
          type="button"
          className="dashboards-close-btn"
          onClick={onClose}
          aria-label="Close dashboards panel"
        >
          <X size={16} />
        </button>
      </header>

      <div className="dashboards-body">
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
    </section>
  );
}
