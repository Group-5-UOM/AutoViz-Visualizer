import {
  Database,
  Filter,
  BotMessageSquare,
  LayoutDashboard,
  Pencil,
  Plus,
  Settings,
} from 'lucide-react';
import type { SidebarItemId } from '../../types/dashboard';
import './Sidebar.css';

interface SidebarProps {
  collapsed: boolean;
  activeItem: SidebarItemId | null;
  onToggleCollapse: () => void;
  onSelect: (id: SidebarItemId) => void;
}

const topItems: { id: SidebarItemId; label: string; icon: typeof Plus }[] = [
  { id: 'add', label: 'Add', icon: Plus },
  { id: 'setup', label: 'Setup', icon: Pencil },
  { id: 'filter', label: 'Filter', icon: Filter },
  { id: 'ai-chat', label: 'AI Chat', icon: BotMessageSquare },
  { id: 'data', label: 'Data', icon: Database },
  { id: 'dashboards', label: 'Dashboards', icon: LayoutDashboard },
];

const bottomItems: { id: SidebarItemId; label: string; icon: typeof Plus }[] = [
  { id: 'settings', label: 'Settings', icon: Settings },
];

export function Sidebar({
  collapsed,
  activeItem,
  onToggleCollapse,
  onSelect,
}: SidebarProps) {
  return (
    <aside
      id="sidebar"
      className={`board-sidebar ${collapsed ? 'is-collapsed' : ''}`}
      aria-label="Board tools"
    >
      <div className="sidebar-inner">
        <div className="sidebar-top">
          {topItems.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              className={`sidebar-btn ${activeItem === id ? 'is-active' : ''}`}
              onClick={() => onSelect(id)}
              title={label}
            >
              <span className="sidebar-icon-wrap">
                <Icon size={18} strokeWidth={1.75} />
              </span>
              <span className="sidebar-label">{label}</span>
            </button>
          ))}
        </div>

        <div className="sidebar-bottom">
          {bottomItems.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              className={`sidebar-btn ${activeItem === id ? 'is-active' : ''}`}
              onClick={() => onSelect(id)}
              title={label}
            >
              <span className="sidebar-icon-wrap">
                <Icon size={18} strokeWidth={1.75} />
              </span>
              <span className="sidebar-label">{label}</span>
            </button>
          ))}

          <button
            type="button"
            className="sidebar-collapse-btn"
            onClick={onToggleCollapse}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            <span className="collapse-chevrons" aria-hidden>
              {collapsed ? '›' : '‹'}
            </span>
          </button>
        </div>
      </div>
    </aside>
  );
}
