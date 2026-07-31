import { useState } from 'react';
import html2canvas from 'html2canvas';
import { Sidebar } from '../components/layout/Sidebar';
import { TopBar } from '../components/layout/TopBar';
import { ChatPanel } from '../components/chat/ChatPanel';
import { DashboardCanvas } from '../components/canvas/DashboardCanvas';
import { DashboardsPanel } from '../components/layout/DashboardsPanel';
import { DatasetModal } from '../components/layout/DatasetModal';
import { SaveDashboardModal } from '../components/layout/SaveDashboardModal';
import { useDashboard } from '../hooks/useDashboard';
import { ApiError } from '../lib/api';
import { uploadDataset, type DatasetMetadata } from '../lib/datasets';
import { getDashboard, getChart, type DashboardResult } from '../lib/dashboards';
import { defaultDashboardName } from '../lib/dashboardSync';
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
  const [renameOpen, setRenameOpen] = useState(false);

  const {
    dashboard,
    messages,
    isThinking,
    saveStatus,
    lastSavedAt,
    saveError,
    selectWidget,
    updateWidget,
    deleteWidget,
    sendMessage,
    saveNow,
    renameDashboard,
    loadDashboardState,
    resetForDataset,
  } = useDashboard(dataset?.datasetId ?? null, dataset?.fileName ?? null);

  const handleLoadDashboard = async (selected: DashboardResult) => {
    try {
      // Flush first: the board being replaced may have edits still on the
      // autosave timer, and loading throws away the state they live in.
      await saveNow();
      const fullDashboard = await getDashboard(selected.id);

      const loadedWidgets = await Promise.all(
        fullDashboard.widgets.map(async (w) => {
          const chartData = await getChart(w.chart_id);
          return {
            id: `chart-${w.id}`,
            title: chartData.name,
            explanation: '',
            vegaLiteSpec: chartData.vega_lite_spec,
            x: w.x,
            y: w.y,
            width: w.w,
            height: w.h,
            backendChartId: w.chart_id,
          };
        })
      );

      loadDashboardState(selected.id, selected.name, loadedWidgets);
      setActiveItem('ai-chat');
      setChatOpen(true);
    } catch (err) {
      console.error('Failed to load dashboard:', err);
      alert('Failed to load dashboard.');
    }
  };

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

  // The canvas already saves itself. Pressing Save flushes immediately, and —
  // the first time only — asks what the board should be called, since until
  // then it is wearing a name autosave invented from the CSV.
  const handleSaveDashboard = () => {
    if (dashboard.nameIsAuto !== false) {
      setRenameOpen(true);
      return;
    }
    void saveNow();
  };

  const handleExportDashboard = async () => {
    const el = document.querySelector('.dashboard-canvas') as HTMLElement;
    if (!el) return;
    try {
      const canvas = await html2canvas(el, { backgroundColor: '#f4f5f7' });
      const link = document.createElement('a');
      link.download = `dashboard-${dataset?.fileName || 'export'}.png`;
      link.href = canvas.toDataURL('image/png');
      link.click();
    } catch (err) {
      console.error('Failed to export dashboard:', err);
    }
  };

  return (
    <div className="board-app">
      <TopBar
        title={dashboard.dashboardName || 'Untitled dashboard'}
        sidebarCollapsed={sidebarCollapsed}
        chatOpen={chatOpen}
        widgetCount={dashboard.widgets.length}
        userEmail={userEmail}
        saveStatus={saveStatus}
        lastSavedAt={lastSavedAt}
        saveError={saveError}
        onToggleSidebar={() => setSidebarCollapsed((v) => !v)}
        onToggleChat={() => {
          setChatOpen((v) => {
            const next = !v;
            if (next) setActiveItem('ai-chat');
            return next;
          });
        }}
        onSave={handleSaveDashboard}
        onRename={() => setRenameOpen(true)}
        onExport={handleExportDashboard}
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
          open={chatOpen && activeItem !== 'dashboards'}
          messages={messages}
          isThinking={isThinking}
          disabled={!dataset}
          disabledReason="Add a CSV file to the canvas to start chatting."
          onClose={() => setChatOpen(false)}
          onSend={sendMessage}
          onFocusChart={(chartId) => selectWidget(chartId)}
        />

        <DashboardsPanel
          open={activeItem === 'dashboards'}
          currentDashboardId={dashboard.dashboardId}
          onClose={() => setActiveItem(chatOpen ? 'ai-chat' : null)}
          onSelect={handleLoadDashboard}
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
            onCsvSelected={handleCsvSelected}
            uploading={uploading}
          />
        )}
        {renameOpen && (
          <SaveDashboardModal
            initialName={dashboard.dashboardName ?? defaultDashboardName(dataset?.fileName)}
            onCancel={() => setRenameOpen(false)}
            onConfirm={(name) => {
              renameDashboard(name);
              setRenameOpen(false);
            }}
          />
        )}
      </div>
    </div>
  );
}
