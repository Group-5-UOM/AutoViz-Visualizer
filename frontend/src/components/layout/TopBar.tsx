import { Download, KeyRound, LogOut, Menu, PanelLeft, Share2, Save, FilePlus2 } from 'lucide-react';
import './TopBar.css';

interface TopBarProps {
  title: string;
  sidebarCollapsed: boolean;
  userEmail?: string;
  username?: string;
  onToggleSidebar: () => void;
  onRename: () => void;
  onExport: () => void;
  onSave?: () => void;
  saveStatus?: 'idle' | 'dirty' | 'saving' | 'saved' | 'error';
  onNewDashboard?: () => void;
  onSetPassword?: () => void;
  onLogout?: () => void | Promise<void>;
  /** Used to disable Export when the canvas has no charts. */
  canExport?: boolean;
}

export function TopBar({
  title,
  sidebarCollapsed,
  userEmail,
  username,
  onToggleSidebar,
  onRename,
  onExport,
  onSave,
  saveStatus,
  onNewDashboard,
  onSetPassword,
  onLogout,
  canExport = true,
}: TopBarProps) {
  const displayName = username || userEmail?.split('@')[0] || userEmail;

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
        <button type="button" className="topbar-text-btn" disabled title="Coming soon">
          <Share2 size={15} />
          Share
        </button>
        {onNewDashboard && (
          <button
            type="button"
            className="topbar-primary-btn"
            style={{ backgroundColor: '#3b82f6', marginRight: '8px' }}
            onClick={onNewDashboard}
            title="Create a new dashboard for this dataset"
          >
            <FilePlus2 size={15} />
            New
          </button>
        )}
        {onSave && (
          <button
            type="button"
            className="topbar-primary-btn"
            style={{ 
              backgroundColor: saveStatus === 'saved' ? '#6b7280' : saveStatus === 'error' ? '#ef4444' : '#10b981', 
              marginRight: '8px',
              cursor: saveStatus === 'saving' ? 'wait' : 'pointer',
              opacity: saveStatus === 'saving' ? 0.7 : 1
            }}
            onClick={onSave}
            disabled={saveStatus === 'saving' || saveStatus === 'saved'}
            title={saveStatus === 'error' ? 'Failed to save. Click to retry.' : 'Save dashboard charts and positions'}
          >
            <Save size={15} />
            {saveStatus === 'saving' ? 'Saving...' : saveStatus === 'saved' ? 'Saved' : saveStatus === 'error' ? 'Error' : 'Save'}
          </button>
        )}
        <button
          type="button"
          className="topbar-primary-btn"
          onClick={onExport}
          disabled={!canExport}
          title={!canExport ? 'Add a chart first' : 'Export the canvas as a PNG'}
        >
          <Download size={15} />
          Export
        </button>

        {displayName && (
          <div className="topbar-user">
            <span className="topbar-user-name" title={userEmail || displayName}>
              {displayName}
            </span>
            {onSetPassword && (
              <button
                type="button"
                className="topbar-icon-btn"
                onClick={onSetPassword}
                title="Set a password"
                aria-label="Set a password"
              >
                <KeyRound size={16} />
              </button>
            )}
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
