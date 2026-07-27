import { useState } from 'react';
import { Sidebar } from '../components/layout/Sidebar';
import { TopBar } from '../components/layout/TopBar';
import { ChatPanel } from '../components/chat/ChatPanel';
import { DashboardCanvas } from '../components/canvas/DashboardCanvas';
import { DatasetModal } from '../components/layout/DatasetModal';
import { useDashboard } from '../hooks/useDashboard';
import { ApiError } from '../lib/api';
import { uploadDataset, type DatasetMetadata } from '../lib/datasets';
import type { SidebarItemId } from '../types/dashboard';
import '../App.css';

interface BoardPageProps {
  userEmail: string;
  onLogout: () => void | Promise<void>;
}

interface DatasetInfo {
  datasetId: string;
  fileName: string;
  rowCount: number;
  columnCount: number;
}

export function BoardPage({ userEmail, onLogout }: BoardPageProps) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [chatOpen, setChatOpen] = useState(true);
  const [activeItem, setActiveItem] = useState<SidebarItemId | null>('ai-chat');
  const [dataset, setDataset] = useState<DatasetInfo | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const {
    dashboard,
    messages,
    isThinking,
    selectWidget,
    updateWidget,
    deleteWidget,
    sendMessage,
    resetForDataset,
  } = useDashboard(dataset?.datasetId ?? null);

  const handleSidebarSelect = (id: SidebarItemId) => {
    setActiveItem(id);
    if (id === 'ai-chat') {
      setChatOpen(true);
    }
  };

  const handleCsvSelected = async (file: File) => {
    setUploadError(null);
    setUploading(true);
    try {
      const result = await uploadDataset(file);
      // Charts and the agent thread belong to the previous dataset — the new
      // CSV has different columns, so carrying either forward is wrong.
      if (result.dataset_id !== dataset?.datasetId) {
        resetForDataset();
      }
      setDataset({
        datasetId: result.dataset_id,
        fileName: result.logical_name || file.name,
        rowCount: result.row_count,
        columnCount: result.column_count,
      });
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Upload failed.';
      setUploadError(message);
    } finally {
      setUploading(false);
    }
  };

  const handleExistingDatasetSelected = (selected: DatasetMetadata) => {
    if (selected.dataset_id !== dataset?.datasetId) {
      resetForDataset();
    }
    setDataset({
      datasetId: selected.dataset_id,
      fileName: selected.logical_name,
      rowCount: selected.row_count,
      columnCount: selected.column_count,
    });
    setActiveItem('ai-chat');
    setChatOpen(true);
  };

  return (
    <div className="board-app">
      <TopBar
        title="Untitled dashboard"
        sidebarCollapsed={sidebarCollapsed}
        chatOpen={chatOpen}
        widgetCount={dashboard.widgets.length}
        userEmail={userEmail}
        onToggleSidebar={() => setSidebarCollapsed((v) => !v)}
        onToggleChat={() => {
          setChatOpen((v) => {
            const next = !v;
            if (next) setActiveItem('ai-chat');
            return next;
          });
        }}
        onLogout={onLogout}
      />

      <div className="board-body">
        <Sidebar
          collapsed={sidebarCollapsed}
          activeItem={activeItem}
          onToggleCollapse={() => setSidebarCollapsed((v) => !v)}
          onSelect={handleSidebarSelect}
        />

        <ChatPanel
          open={chatOpen}
          messages={messages}
          isThinking={isThinking}
          disabled={!dataset}
          disabledReason="Add a CSV file to the canvas to start chatting."
          onClose={() => setChatOpen(false)}
          onSend={sendMessage}
          onFocusChart={(chartId) => selectWidget(chartId)}
        />

        <DashboardCanvas
          widgets={dashboard.widgets}
          selectedWidgetId={dashboard.selectedWidgetId}
          dataset={dataset}
          uploading={uploading}
          uploadError={uploadError}
          onSelect={selectWidget}
          onUpdate={updateWidget}
          onDelete={deleteWidget}
          onCsvSelected={handleCsvSelected}
        />

        {activeItem === 'data' && (
          <DatasetModal
            currentDatasetId={dataset?.datasetId}
            onClose={() => setActiveItem(chatOpen ? 'ai-chat' : null)}
            onSelect={handleExistingDatasetSelected}
          />
        )}
      </div>
    </div>
  );
}
