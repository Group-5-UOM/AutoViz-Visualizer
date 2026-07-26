import { Download, LogOut, Menu, PanelLeft, Save, Share2 } from 'lucide-react';
import './TopBar.css';

interface TopBarProps {
  title: string;
  sidebarCollapsed: boolean;
  chatOpen: boolean;
  widgetCount: number;
  userEmail?: string;
  username?: string;
  onToggleSidebar: () => void;
  onToggleChat: () => void;
  onLogout?: () => void | Promise<void>;
}

export function TopBar({
  title,
  sidebarCollapsed,
  chatOpen,
  widgetCount,
  userEmail,
  username,
  onToggleSidebar,
  onToggleChat,
  onLogout,
}: TopBarProps) {
  const displayName = username || userEmail?.split('@')[0];
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

        <button type="button" className="topbar-text-btn" disabled title="Coming soon">
          <Save size={15} />
          Save
        </button>
        <button type="button" className="topbar-text-btn" disabled title="Coming soon">
          <Share2 size={15} />
          Share
        </button>
        <button type="button" className="topbar-primary-btn" disabled title="Coming soon">
          <Download size={15} />
          Export
        </button>

        {displayName && (
          <div className="topbar-user">
            <span className="topbar-user-avatar" aria-hidden>
              {displayName.charAt(0).toUpperCase()}
            </span>
            <span className="topbar-user-name" title={userEmail || displayName}>
              {displayName}
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
