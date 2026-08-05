import { useEffect, useMemo, useState } from 'react';
import html2canvas from 'html2canvas';
import { Sidebar } from '../components/layout/Sidebar';
import { TopBar } from '../components/layout/TopBar';
import { AccountPasswordModal } from '../components/layout/AccountPasswordModal';
import { AddPanel } from '../components/layout/AddPanel';
import { SetupPanel, buildChartPrompt } from '../components/layout/SetupPanel';
import { FilterPanel } from '../components/layout/FilterPanel';
import { ChatPanel } from '../components/chat/ChatPanel';
import { DashboardCanvas } from '../components/canvas/DashboardCanvas';
import { DatasetSheet } from '../components/canvas/DatasetSheet';
import { StylePanel } from '../components/canvas/StylePanel';
import {
  DashboardsPanel,
  type SavedDatasetEntry,
} from '../components/layout/DashboardsPanel';
import { DatasetModal } from '../components/layout/DatasetModal';
import { NameUploadModal, namedCsvFile } from '../components/layout/NameUploadModal';
import { SaveDashboardModal } from '../components/layout/SaveDashboardModal';
import { useDashboard } from '../hooks/useDashboard';
import { ApiError } from '../lib/api';
import { fetchMe } from '../lib/auth';
import { loadBoardSession, saveBoardSession } from '../lib/boardSession';
import { inferChartType } from '../lib/chartType';
import { uploadDataset, type DatasetMetadata } from '../lib/datasets';
import { getDashboard, getChart, type DashboardResult } from '../lib/dashboards';
import { defaultDashboardName } from '../lib/dashboardSync';
import type { ChartStyle, ChartType, ChartWidget, SidebarItemId } from '../types/dashboard';
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
  return defaultDashboardName(datasetFileName);
}

function openAiChat(
  setActiveItem: (id: SidebarItemId | null) => void,
  setChatOpen: (v: boolean) => void,
) {
  setActiveItem('ai-chat');
  setChatOpen(true);
}

async function widgetsFromDashboard(selected: DashboardResult): Promise<ChartWidget[]> {
  const fullDashboard = await getDashboard(selected.id);
  return Promise.all(
    fullDashboard.widgets.map(async (w) => {
      const chartData = await getChart(w.chart_id);
      const chartType =
        typeof chartData.chart_spec?.type === 'string'
          ? chartData.chart_spec.type
          : undefined;
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
        chartType,
        style: (chartData.chart_spec?.style as ChartStyle | undefined) ?? undefined,
        specVersion: 0,
        syncedSpecVersion: 0,
      };
    }),
  );
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
  const [chartTypeFilter, setChartTypeFilter] = useState<ChartType[]>([]);
  const [browseOpen, setBrowseOpen] = useState(false);
  const [pendingUpload, setPendingUpload] = useState<File | null>(null);

  useEffect(() => {
    let cancelled = false;
    void fetchMe()
      .then((me) => {
        if (!cancelled) setHasPassword(Boolean(me.has_password));
      })
      .catch(() => {
        /* ignore */
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
    replaceMessages,
    resetForDataset,
  } = useDashboard(dataset?.datasetId ?? null, dataset?.fileName ?? null);

  // Persist chat + dashboard link per dataset so Dashboards can restore them.
  useEffect(() => {
    if (!dataset?.datasetId) return;
    saveBoardSession(dataset.datasetId, {
      dashboardId: dashboard.dashboardId ?? null,
      messages,
    });
  }, [dataset?.datasetId, dashboard.dashboardId, messages]);

  const closeSideTool = () => setActiveItem(chatOpen ? 'ai-chat' : null);
  const setupMessages = messages.slice(-8);

  const chartCounts = useMemo(() => {
    const counts: Partial<Record<ChartType | 'other', number>> = {};
    for (const w of dashboard.widgets) {
      const t = inferChartType(w);
      counts[t] = (counts[t] ?? 0) + 1;
    }
    return counts;
  }, [dashboard.widgets]);

  const visibleWidgets = useMemo(() => {
    if (chartTypeFilter.length === 0) return dashboard.widgets;
    return dashboard.widgets.filter((w) => {
      const t = inferChartType(w);
      return t !== 'other' && chartTypeFilter.includes(t);
    });
  }, [dashboard.widgets, chartTypeFilter]);

  const styleWidget = dashboard.widgets.find((w) => w.id === styleWidgetId) ?? null;

  const applyLoadedCanvas = async (
    selected: DashboardResult,
    restoredMessages?: typeof messages,
  ) => {
    const loadedWidgets = await widgetsFromDashboard(selected);
    loadDashboardState(selected.id, selected.name, loadedWidgets, restoredMessages);
  };

  const handleLoadSavedDataset = async (entry: SavedDatasetEntry) => {
    try {
      if (dataset?.datasetId && dataset.datasetId !== entry.dataset.dataset_id) {
        await saveNow();
        saveBoardSession(dataset.datasetId, {
          dashboardId: dashboard.dashboardId ?? null,
          messages,
        });
        resetForDataset();
      }

      setChartTypeFilter([]);
      setDataset({
        datasetId: entry.dataset.dataset_id,
        fileName: entry.dataset.logical_name,
        rowCount: entry.dataset.row_count,
        columnCount: entry.dataset.column_count,
      });

      const session = loadBoardSession(entry.dataset.dataset_id);
      const title = defaultDashboardName(entry.dataset.logical_name);

      if (entry.dashboard) {
        await applyLoadedCanvas(entry.dashboard, session?.messages);
        if (!session?.messages?.length) {
          /* loadDashboardState already set a loaded message */
        }
      } else {
        renameDashboard(title);
        if (session?.messages?.length) {
          replaceMessages(session.messages);
        }
      }

      openAiChat(setActiveItem, setChatOpen);
    } catch (err) {
      console.error('Failed to load saved dataset:', err);
      alert('Failed to load dataset canvas.');
    }
  };

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
      if (dataset?.datasetId) {
        saveBoardSession(dataset.datasetId, {
          dashboardId: dashboard.dashboardId ?? null,
          messages,
        });
      }
      const result = await uploadDataset(file);
      if (result.dataset_id !== dataset?.datasetId) {
        resetForDataset();
        setChartTypeFilter([]);
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
      openAiChat(setActiveItem, setChatOpen);
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

  const handleExistingDatasetSelected = async (selected: DatasetMetadata) => {
    setBrowseOpen(false);
    let dashboard: DashboardResult | null = null;
    let chartCount = 0;
    try {
      const { listDashboards } = await import('../lib/dashboards');
      const { dashboards } = await listDashboards();
      for (const dash of dashboards) {
        if (!dash.widgets.length) continue;
        const chart = await getChart(dash.widgets[0].chart_id);
        if (chart.dataset_id === selected.dataset_id) {
          dashboard = dash;
          chartCount = dash.widgets.length;
          break;
        }
      }
    } catch {
      /* optional enrichment */
    }
    await handleLoadSavedDataset({ dataset: selected, dashboard, chartCount });
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
    void sendMessage(text);
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
          onClose={closeSideTool}
          onCsvSelected={handleCsvPicked}
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
          selectedTypes={chartTypeFilter}
          chartCounts={chartCounts}
          onClose={closeSideTool}
          onChange={setChartTypeFilter}
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
          referenceable={dashboard.widgets.filter((w) => w.agentChartId)}
          referencedWidgetId={referencedWidgetId}
          onReference={referenceWidget}
        />

        <DashboardsPanel
          open={showDashboards}
          currentDatasetId={dataset?.datasetId}
          onClose={closeSideTool}
          onSelect={(entry) => void handleLoadSavedDataset(entry)}
        />

        {showDatasetSheet && dataset ? (
          <DatasetSheet
            datasetId={dataset.datasetId}
            fileName={dataset.fileName}
            rowCount={dataset.rowCount}
            columnCount={dataset.columnCount}
            onClose={() => openAiChat(setActiveItem, setChatOpen)}
            onSaved={handleCsvSelected}
          />
        ) : (
          <DashboardCanvas
            widgets={visibleWidgets}
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
                openAiChat(setActiveItem, setChatOpen);
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
