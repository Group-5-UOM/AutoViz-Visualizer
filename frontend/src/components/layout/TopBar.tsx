import { Download, LogOut, Menu, PanelLeft, Save, Share2 } from 'lucide-react';
import type { SaveStatus } from '../../types/dashboard';
import './TopBar.css';

interface TopBarProps {
  title: string;
  sidebarCollapsed: boolean;
  chatOpen: boolean;
  widgetCount: number;
  userEmail?: string;
  saveStatus: SaveStatus;
  /** When the last successful save landed, shown as the status tooltip. */
  lastSavedAt: number | null;
  saveError?: string | null;
  onToggleSidebar: () => void;
  onToggleChat: () => void;
  onSave: () => void;
  onRename: () => void;
  onExport: () => void;
  onLogout?: () => void | Promise<void>;
}

const STATUS_TEXT: Record<SaveStatus, string> = {
  idle: '',
  dirty: 'Unsaved changes',
  saving: 'Saving…',
  saved: 'All changes saved',
  error: 'Save failed',
};

export function TopBar({
  title,
  sidebarCollapsed,
  chatOpen,
  widgetCount,
  userEmail,
  saveStatus,
  lastSavedAt,
  saveError,
  onToggleSidebar,
  onToggleChat,
  onSave,
  onRename,
  onExport,
  onLogout,
}: TopBarProps) {
  const statusText = STATUS_TEXT[saveStatus];
  // Nothing to flush and nothing to retry — the button would be a no-op.
  const saveDisabled = saveStatus === 'saving' || saveStatus === 'idle';

  return (
    <header className="board-topbar">
      <div className="topbar-left">
        <button
          type="button"
          className="topbar-icon-btn"
          onClick={onToggleSidebar}
          title={sidebarCollapsed ? 'Show sidebar' : 'Hide sidebar'}
          aria-label={sidebarCollapsed ? 'Show sidebar' : 'Hide sidebar'}
        >
          {sidebarCollapsed ? <Menu size={18} /> : <PanelLeft size={18} />}
        </button>

        <div className="brand-block">
          <span className="brand-mark" aria-hidden />
          <div className="brand-text">
            <span className="brand-name">AutoViz AI</span>
            <span className="brand-divider">/</span>
            <button
              type="button"
              className="dashboard-title"
              onClick={onRename}
              title="Rename this dashboard"
            >
              {title}
            </button>
          </div>
        </div>
      </div>

      <div className="topbar-right">
        <span className="widget-count">
          {widgetCount} {widgetCount === 1 ? 'chart' : 'charts'}
        </span>

        {statusText && (
          <span
            className={`topbar-save-status is-${saveStatus}`}
            role={saveStatus === 'error' ? 'alert' : undefined}
            title={
              saveStatus === 'error'
                ? (saveError ?? undefined)
                : lastSavedAt
                  ? `Last saved at ${new Date(lastSavedAt).toLocaleTimeString()}`
                  : undefined
            }
          >
            {statusText}
          </span>
        )}

        <button
          type="button"
          className={`topbar-text-btn ${chatOpen ? 'is-active' : ''}`}
          onClick={onToggleChat}
        >
          AI Chat
        </button>

        <button
          type="button"
          className="topbar-text-btn"
          onClick={onSave}
          disabled={saveDisabled}
          title={saveStatus === 'error' ? 'Try saving again' : 'Save now'}
        >
          <Save size={15} />
          {saveStatus === 'error' ? 'Retry' : 'Save'}
        </button>
        <button type="button" className="topbar-text-btn" disabled title="Coming soon">
          <Share2 size={15} />
          Share
        </button>
        <button
          type="button"
          className="topbar-primary-btn"
          onClick={onExport}
          disabled={widgetCount === 0}
          title={widgetCount === 0 ? 'Add a chart first' : 'Export the canvas as a PNG'}
        >
          <Download size={15} />
          Export
        </button>

        {userEmail && (
          <div className="topbar-user">
            <span className="topbar-user-email" title={userEmail}>
              {userEmail}
            </span>
            {onLogout && (
              <button
                type="button"
                className="topbar-icon-btn"
                onClick={onLogout}
                title="Sign out"
                aria-label="Sign out"
              >
                <LogOut size={16} />
              </button>
            )}
          </div>
        )}
      </div>
    </header>
  );
}
