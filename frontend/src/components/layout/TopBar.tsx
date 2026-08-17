import { useEffect, useRef, useState } from 'react';
import {
  ChevronDown,
  Download,
  FileImage,
  FileText,
  KeyRound,
  Link2,
  LogOut,
  Menu,
  PanelLeft,
  Share2,
  Save,
  FilePlus2,
} from 'lucide-react';
import type { ExportFormat } from '../../lib/exportDashboard';
import { ShareDropdownPanel } from './ShareDropdownPanel';
import './TopBar.css';

interface TopBarProps {
  title: string;
  sidebarCollapsed: boolean;
  userEmail?: string;
  username?: string;
  onToggleSidebar: () => void;
  onRename: () => void;
  onExport: (format: ExportFormat) => void;
  exporting?: ExportFormat | null;
  shareDashboardId?: string | null;
  onSave?: () => void;
  saveStatus?: 'idle' | 'dirty' | 'saving' | 'saved' | 'error';
  /**
   * Why the last save failed. Shown on the button, because "Error" on its own
   * tells the user something went wrong and nothing about what.
   */
  saveError?: string | null;
  onNewDashboard?: () => void;
  onSetPassword?: () => void;
  /** Opens the MCP connection-link panel. */
  onOpenConnections?: () => void;
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
  exporting = null,
  shareDashboardId,
  onSave,
  saveStatus,
  saveError,
  onNewDashboard,
  onSetPassword,
  onOpenConnections,
  onLogout,
  canExport = true,
}: TopBarProps) {
  const displayName = username || userEmail?.split('@')[0] || userEmail;
  const [exportOpen, setExportOpen] = useState(false);
  const [shareMenuOpen, setShareMenuOpen] = useState(false);
  const exportRef = useRef<HTMLDivElement>(null);
  const shareRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!exportOpen && !shareMenuOpen) return;
    const onPointerDown = (e: PointerEvent) => {
      const target = e.target as Node;
      if (exportOpen && !exportRef.current?.contains(target)) {
        setExportOpen(false);
      }
      if (shareMenuOpen && !shareRef.current?.contains(target)) {
        setShareMenuOpen(false);
      }
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setExportOpen(false);
        setShareMenuOpen(false);
      }
    };
    window.addEventListener('pointerdown', onPointerDown);
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('pointerdown', onPointerDown);
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [exportOpen, shareMenuOpen]);

  const runExport = (format: ExportFormat) => {
    setExportOpen(false);
    onExport(format);
  };

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
        {shareDashboardId && (
          <div className="topbar-export-dropdown" ref={shareRef}>
            <button 
              type="button" 
              className="topbar-text-btn" 
              onClick={() => setShareMenuOpen(!shareMenuOpen)} 
              title="Share dashboard"
            >
              <Share2 size={15} />
              Share
              <ChevronDown size={14} style={{ marginLeft: '-2px', opacity: 0.8 }} />
            </button>
            
            {shareMenuOpen && (
              <ShareDropdownPanel dashboardId={shareDashboardId} />
            )}
          </div>
        )}
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
            title={
              saveStatus === 'error'
                ? `Failed to save${saveError ? `: ${saveError}` : ''}. Click to retry.`
                : 'Save dashboard charts and positions'
            }
          >
            <Save size={15} />
            {saveStatus === 'saving' ? 'Saving...' : saveStatus === 'saved' ? 'Saved' : saveStatus === 'error' ? 'Retry save' : 'Save'}
          </button>
        )}
        <div className="topbar-export" ref={exportRef}>
          <button
            type="button"
            className="topbar-primary-btn"
            onClick={() => setExportOpen((open) => !open)}
            disabled={!canExport || exporting !== null}
            aria-haspopup="menu"
            aria-expanded={exportOpen}
            title={!canExport ? 'Add a chart first' : 'Export this dashboard'}
          >
            <Download size={15} />
            {exporting === 'pdf' ? 'Making PDF…' : exporting === 'png' ? 'Making image…' : 'Export'}
            <ChevronDown size={13} />
          </button>

          {exportOpen && (
            <div className="topbar-menu" role="menu" aria-label="Export format">
              <button type="button" role="menuitem" onClick={() => runExport('png')}>
                <FileImage size={15} />
                <span>
                  PNG image
                  <small>One picture of the canvas</small>
                </span>
              </button>
              <button type="button" role="menuitem" onClick={() => runExport('pdf')}>
                <FileText size={15} />
                <span>
                  PDF document
                  <small>A single page, sized to fit</small>
                </span>
              </button>
            </div>
          )}
        </div>

        {displayName && (
          <div className="topbar-user">
            <span className="topbar-user-name" title={userEmail || displayName}>
              {displayName}
            </span>
            {onOpenConnections && (
              <button
                type="button"
                className="topbar-icon-btn"
                onClick={onOpenConnections}
                title="Connections — link an AI assistant"
                aria-label="Connections — link an AI assistant"
              >
                <Link2 size={16} />
              </button>
            )}
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
