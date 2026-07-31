import { Download, LogOut, Menu, PanelLeft, Save, Share2 } from 'lucide-react';
import './TopBar.css';

interface TopBarProps {
  title: string;
  sidebarCollapsed: boolean;
  chatOpen: boolean;
  widgetCount: number;
  userEmail?: string;
  onToggleSidebar: () => void;
  onToggleChat: () => void;
  onSave: () => void;
  onExport: () => void;
  onLogout?: () => void | Promise<void>;
}

export function TopBar({
  title,
  sidebarCollapsed,
  chatOpen,
  widgetCount,
  userEmail,
  onToggleSidebar,
  onToggleChat,
  onSave,
  onExport,
  onLogout,
}: TopBarProps) {
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
            <span className="dashboard-title">{title}</span>
          </div>
        </div>
      </div>

      <div className="topbar-right">
        <span className="widget-count">
          {widgetCount} {widgetCount === 1 ? 'chart' : 'charts'}
        </span>

        <button
          type="button"
          className={`topbar-text-btn ${chatOpen ? 'is-active' : ''}`}
          onClick={onToggleChat}
        >
          AI Chat
        </button>

        <button type="button" className="topbar-text-btn" onClick={onSave} title="Save Dashboard">
          <Save size={15} />
          Save
        </button>
        <button type="button" className="topbar-text-btn" disabled title="Coming soon">
          <Share2 size={15} />
          Share
        </button>
        <button type="button" className="topbar-primary-btn" onClick={onExport} title="Export Dashboard">
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
