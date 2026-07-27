import { useState } from 'react';
import html2canvas from 'html2canvas';
import { Sidebar } from '../components/layout/Sidebar';
import { TopBar } from '../components/layout/TopBar';
import { ChatPanel } from '../components/chat/ChatPanel';
import { DashboardCanvas } from '../components/canvas/DashboardCanvas';
import { DashboardsModal } from '../components/layout/DashboardsModal';
import { DatasetModal } from '../components/layout/DatasetModal';
import { useDashboard } from '../hooks/useDashboard';
import { ApiError } from '../lib/api';
import { uploadDataset, type DatasetMetadata } from '../lib/datasets';
import { createDashboard, saveChart, updateDashboard, getDashboard, getChart, type DashboardResult } from '../lib/dashboards';
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
    setDashboardMeta,
    updateWidget,
    deleteWidget,
    sendMessage,
    loadDashboardState,
    resetForDataset,
  } = useDashboard(dataset?.datasetId ?? null);

  const handleLoadDashboard = async (selected: DashboardResult) => {
    try {
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

  const handleSaveDashboard = async () => {
    try {
      let dashId = dashboard.dashboardId;
      let dashName = dashboard.dashboardName;

      if (!dashId) {
        const name = window.prompt('Enter a name for this dashboard:', 'My Dashboard');
        if (!name) return;
        const created = await createDashboard(name);
        dashId = created.id;
        dashName = created.name;
        setDashboardMeta(dashId, dashName);
      }

      for (const w of dashboard.widgets) {
        if (!w.backendChartId) {
          const saved = await saveChart({
            name: w.title,
            vega_lite_spec: w.vegaLiteSpec,
            dataset_id: dataset?.datasetId,
          });
          updateWidget(w.id, { backendChartId: saved.id });
          w.backendChartId = saved.id;
        }
      }

      if (dashId) {
        const widgets = dashboard.widgets.map((w, i) => ({
          chart_id: w.backendChartId!,
          x: w.x,
          y: w.y,
          w: w.width,
          h: w.height,
          order: i,
        }));
        await updateDashboard(dashId, dashName, widgets);
        alert('Dashboard saved successfully!');
      }
    } catch (err) {
      console.error('Failed to save dashboard:', err);
      alert('Failed to save dashboard.');
    }
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
        onToggleSidebar={() => setSidebarCollapsed((v) => !v)}
        onToggleChat={() => {
          setChatOpen((v) => {
            const next = !v;
            if (next) setActiveItem('ai-chat');
            return next;
          });
        }}
        onSave={handleSaveDashboard}
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

        {activeItem === 'dashboards' && (
          <DashboardsModal
            currentDashboardId={dashboard.dashboardId}
            onClose={() => setActiveItem(chatOpen ? 'ai-chat' : null)}
            onSelect={handleLoadDashboard}
          />
        )}
      </div>
    </div>
  );
}
