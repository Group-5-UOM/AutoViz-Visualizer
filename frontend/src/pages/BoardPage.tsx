import { useEffect, useState } from 'react';
import html2canvas from 'html2canvas';
import { Sidebar } from '../components/layout/Sidebar';
import { TopBar } from '../components/layout/TopBar';
import { AccountPasswordModal } from '../components/layout/AccountPasswordModal';
import { AddPanel } from '../components/layout/AddPanel';
import { SetupPanel, buildChartPrompt } from '../components/layout/SetupPanel';
import {
  FilterPanel,
  formatFiltersForPrompt,
  type BoardFilters,
} from '../components/layout/FilterPanel';
import { ChatPanel } from '../components/chat/ChatPanel';
import { DashboardCanvas } from '../components/canvas/DashboardCanvas';
import { DatasetSheet } from '../components/canvas/DatasetSheet';
import { StylePanel } from '../components/canvas/StylePanel';
import { DashboardsPanel } from '../components/layout/DashboardsPanel';
import { DatasetModal } from '../components/layout/DatasetModal';
import { NameUploadModal, namedCsvFile } from '../components/layout/NameUploadModal';
import { SaveDashboardModal } from '../components/layout/SaveDashboardModal';
import { useDashboard } from '../hooks/useDashboard';
import { ApiError } from '../lib/api';
import { fetchMe } from '../lib/auth';
import { uploadDataset, type DatasetMetadata } from '../lib/datasets';
import { getDashboard, getChart, type DashboardResult } from '../lib/dashboards';
import { defaultDashboardName } from '../lib/dashboardSync';
import type { ChartStyle, ChartType, SidebarItemId } from '../types/dashboard';
import '../App.css';

interface BoardPageProps {
  userEmail: string;
  username: string;
  onLogout: () => void | Promise<void>;
}

interface DatasetInfo {
  datasetId: string;
  fileName: string;
  rowCount: number;
  columnCount: number;
}

function boardTitle(
  dashboardName: string | undefined,
  datasetFileName: string | null | undefined,
): string {
  if (dashboardName?.trim()) return dashboardName.trim();
  const fromFile = defaultDashboardName(datasetFileName);
  return fromFile;
}

export function BoardPage({ userEmail, username, onLogout }: BoardPageProps) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [chatOpen, setChatOpen] = useState(true);
  const [activeItem, setActiveItem] = useState<SidebarItemId | null>('ai-chat');
  const [dataset, setDataset] = useState<DatasetInfo | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [renameOpen, setRenameOpen] = useState(false);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [hasPassword, setHasPassword] = useState(true);
  const [styleWidgetId, setStyleWidgetId] = useState<string | null>(null);
  const [styleBusy, setStyleBusy] = useState(false);
  const [filters, setFilters] = useState<BoardFilters>({});
  const [browseOpen, setBrowseOpen] = useState(false);
  const [pendingUpload, setPendingUpload] = useState<File | null>(null);

  useEffect(() => {
    let cancelled = false;
    void fetchMe()
      .then((me) => {
        if (!cancelled) setHasPassword(Boolean(me.has_password));
      })
      .catch(() => {
        /* ignore — password button still works */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const {
    dashboard,
    messages,
    isThinking,
    referencedWidgetId,
    referenceWidget,
    selectWidget,
    updateWidget,
    editWidgetStyle,
    deleteWidget,
    sendMessage,
    saveNow,
    renameDashboard,
    loadDashboardState,
    resetForDataset,
  } = useDashboard(dataset?.datasetId ?? null, dataset?.fileName ?? null);

  const closeSideTool = () => setActiveItem(chatOpen ? 'ai-chat' : null);

  // Keep Setup chat focused: only the latest handful of turns.
  const setupMessages = messages.slice(-8);

  const handleLoadDashboard = async (selected: DashboardResult) => {
    try {
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
            // Restored so the style panel opens showing what was actually
            // chosen, rather than defaults over an already-styled render.
            style: (chartData.chart_spec?.style as ChartStyle | undefined) ?? undefined,
            // This spec is, by definition, the one the server holds. Both at
            // zero means reopening a board does not immediately re-upload it.
            specVersion: 0,
            syncedSpecVersion: 0,
          };
        }),
      );

      loadDashboardState(selected.id, selected.name, loadedWidgets);
      setFilters({});
      setActiveItem('ai-chat');
      setChatOpen(true);
    } catch (err) {
      console.error('Failed to load dashboard:', err);
      alert('Failed to load dashboard.');
    }
  };

  // Resolved from live state rather than held in it, so the panel follows the
  // widget through an edit and disappears with it if the chart is deleted.
  const styleWidget = dashboard.widgets.find((w) => w.id === styleWidgetId) ?? null;

  const handleSidebarSelect = (id: SidebarItemId) => {
    if (id === 'settings') {
      setPasswordOpen(true);
      return;
    }
    if (id === 'data') {
      if (!dataset) {
        setBrowseOpen(true);
        return;
      }
      setActiveItem('data');
      setChatOpen(false);
      return;
    }
    if (activeItem === id) {
      setActiveItem(chatOpen ? 'ai-chat' : null);
      return;
    }
    setActiveItem(id);
    if (id === 'ai-chat') {
      setChatOpen(true);
    }
  };

  const handleCsvPicked = async (file: File) => {
    setUploadError(null);
    setPendingUpload(file);
  };

  const handleCsvSelected = async (file: File, boardName?: string) => {
    setUploadError(null);
    setUploading(true);
    try {
      const result = await uploadDataset(file);
      if (result.dataset_id !== dataset?.datasetId) {
        resetForDataset();
        setFilters({});
      }
      const savedName = result.logical_name || file.name;
      setDataset({
        datasetId: result.dataset_id,
        fileName: savedName,
        rowCount: result.row_count,
        columnCount: result.column_count,
      });
      if (boardName?.trim()) {
        renameDashboard(boardName.trim());
      }
      setActiveItem('data');
      setChatOpen(false);
      setBrowseOpen(false);
      setPendingUpload(null);
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

  const handleConfirmUploadName = (displayName: string) => {
    if (!pendingUpload) return;
    const named = namedCsvFile(pendingUpload, displayName);
    void handleCsvSelected(named, displayName.trim());
  };

  const handleExistingDatasetSelected = (selected: DatasetMetadata) => {
    if (selected.dataset_id !== dataset?.datasetId) {
      resetForDataset();
      setFilters({});
    }
    setDataset({
      datasetId: selected.dataset_id,
      fileName: selected.logical_name,
      rowCount: selected.row_count,
      columnCount: selected.column_count,
    });
    renameDashboard(defaultDashboardName(selected.logical_name));
    setActiveItem('data');
    setChatOpen(false);
    setBrowseOpen(false);
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

  const handleSendMessage = (text: string) => {
    const prefix = formatFiltersForPrompt(filters);
    void sendMessage(prefix ? `${prefix}${text}` : text);
  };

  const handleSetupAsk = (chartType: ChartType, question: string) => {
    handleSendMessage(buildChartPrompt(chartType, question));
  };

  const showChat = chatOpen && activeItem === 'ai-chat';
  const showDashboards = activeItem === 'dashboards';
  const showAdd = activeItem === 'add';
  const showSetup = activeItem === 'setup';
  const showFilter = activeItem === 'filter';
  const showDatasetSheet = activeItem === 'data' && Boolean(dataset);

  return (
    <div className="board-app">
      <TopBar
        title={boardTitle(dashboard.dashboardName, dataset?.fileName)}
        sidebarCollapsed={sidebarCollapsed}
        userEmail={userEmail}
        username={username}
        canExport={dashboard.widgets.length > 0}
        onToggleSidebar={() => setSidebarCollapsed((v) => !v)}
        onRename={() => setRenameOpen(true)}
        onExport={handleExportDashboard}
        onSetPassword={() => setPasswordOpen(true)}
        onLogout={onLogout}
      />

      <AccountPasswordModal
        open={passwordOpen}
        hasPassword={hasPassword}
        onClose={() => setPasswordOpen(false)}
        onSaved={() => setHasPassword(true)}
      />

      <div className="board-body">
        <Sidebar
          collapsed={sidebarCollapsed}
          activeItem={activeItem}
          onToggleCollapse={() => setSidebarCollapsed((v) => !v)}
          onSelect={handleSidebarSelect}
        />

        <AddPanel
          open={showAdd}
          uploading={uploading}
          uploadError={uploadError}
          dataset={
            dataset
              ? {
                  fileName: dataset.fileName,
                  rowCount: dataset.rowCount,
                  columnCount: dataset.columnCount,
                }
              : null
          }
          onClose={closeSideTool}
          onCsvSelected={handleCsvPicked}
          onBrowseDatasets={() => setBrowseOpen(true)}
        />

        <SetupPanel
          open={showSetup}
          hasDataset={Boolean(dataset)}
          datasetName={dataset?.fileName}
          isThinking={isThinking}
          messages={setupMessages}
          onClose={closeSideTool}
          onAsk={handleSetupAsk}
        />

        <FilterPanel
          open={showFilter}
          datasetId={dataset?.datasetId ?? null}
          filters={filters}
          onClose={closeSideTool}
          onChange={setFilters}
        />

        <ChatPanel
          open={showChat}
          messages={messages}
          isThinking={isThinking}
          disabled={!dataset}
          disabledReason="Add a CSV file to the canvas to start chatting."
          onClose={() => {
            setChatOpen(false);
            setActiveItem(null);
          }}
          onSend={handleSendMessage}
          onFocusChart={(chartId) => selectWidget(chartId)}
          // Only charts this conversation produced: a chart restored from a
          // saved dashboard has no thread behind it to refine against.
          referenceable={dashboard.widgets.filter((w) => w.agentChartId)}
          referencedWidgetId={referencedWidgetId}
          onReference={referenceWidget}
        />

        <DashboardsPanel
          open={showDashboards}
          currentDashboardId={dashboard.dashboardId}
          onClose={closeSideTool}
          onSelect={handleLoadDashboard}
        />

        {showDatasetSheet && dataset ? (
          <DatasetSheet
            datasetId={dataset.datasetId}
            fileName={dataset.fileName}
            rowCount={dataset.rowCount}
            columnCount={dataset.columnCount}
            onClose={() => setActiveItem(chatOpen ? 'ai-chat' : null)}
            onSaved={handleCsvSelected}
          />
        ) : (
          <DashboardCanvas
            widgets={dashboard.widgets}
            selectedWidgetId={dashboard.selectedWidgetId}
            dataset={dataset}
            uploading={uploading}
            uploadError={uploadError}
            onSelect={selectWidget}
            onUpdate={updateWidget}
            onEditStyle={(id, request) => editWidgetStyle(id, { request })}
            onOpenStyle={setStyleWidgetId}
            onReference={(id) => {
              referenceWidget(referencedWidgetId === id ? null : id);
              if (referencedWidgetId !== id) {
                setActiveItem('ai-chat');
                setChatOpen(true);
              }
            }}
            referencedWidgetId={referencedWidgetId}
            onDelete={deleteWidget}
            onCsvSelected={handleCsvPicked}
            onOpenData={() => {
              if (dataset) {
                setActiveItem('data');
                setChatOpen(false);
              } else {
                setBrowseOpen(true);
              }
            }}
          />
        )}

        {styleWidget && (
          <StylePanel
            widget={styleWidget}
            busy={styleBusy}
            onApply={async (style) => {
              setStyleBusy(true);
              await editWidgetStyle(styleWidget.id, { style });
              setStyleBusy(false);
            }}
            onClose={() => setStyleWidgetId(null)}
          />
        )}

        {browseOpen && (
          <DatasetModal
            currentDatasetId={dataset?.datasetId}
            onClose={() => setBrowseOpen(false)}
            onSelect={handleExistingDatasetSelected}
            onCsvSelected={handleCsvPicked}
            uploading={uploading}
          />
        )}
        {pendingUpload && (
          <NameUploadModal
            file={pendingUpload}
            onCancel={() => setPendingUpload(null)}
            onConfirm={handleConfirmUploadName}
          />
        )}
        {renameOpen && (
          <SaveDashboardModal
            initialName={boardTitle(dashboard.dashboardName, dataset?.fileName)}
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
