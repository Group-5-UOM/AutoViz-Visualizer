import { Download, Menu, PanelLeft, Save, Share2 } from 'lucide-react';
import './TopBar.css';

interface TopBarProps {
  title: string;
  sidebarCollapsed: boolean;
  chatOpen: boolean;
  widgetCount: number;
  onToggleSidebar: () => void;
  onToggleChat: () => void;
}

export function TopBar({
  title,
  sidebarCollapsed,
  chatOpen,
  widgetCount,
  onToggleSidebar,
  onToggleChat,
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
      </div>
    </header>
  );
}
