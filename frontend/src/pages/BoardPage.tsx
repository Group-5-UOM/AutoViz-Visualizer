import { useEffect, useMemo, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Sidebar } from '../components/layout/Sidebar';
import { TopBar } from '../components/layout/TopBar';
import { NoticeStack } from '../components/layout/NoticeStack';
import { AccountPasswordModal } from '../components/layout/AccountPasswordModal';
import { AddPanel } from '../components/layout/AddPanel';
import { SetupPanel, buildChartPrompt } from '../components/layout/SetupPanel';
import { FilterPanel } from '../components/layout/FilterPanel';
import { ChatPanel } from '../components/chat/ChatPanel';
import { DashboardCanvas } from '../components/canvas/DashboardCanvas';
import { DatasetSheet } from '../components/canvas/DatasetSheet';
import { StylePanel } from '../components/canvas/StylePanel';
import {
  DashboardsModal,
  type SavedDatasetEntry,
} from '../components/layout/DashboardsModal';
import { DatasetModal } from '../components/layout/DatasetModal';
import { NameUploadModal, namedCsvFile } from '../components/layout/NameUploadModal';
import { SaveDashboardModal } from '../components/layout/SaveDashboardModal';
import { useDashboard } from '../hooks/useDashboard';
import { useNotices } from '../hooks/useNotices';
import { errorMessage } from '../lib/api';
import { exportDashboard, type ExportFormat } from '../lib/exportDashboard';
import { fetchMe } from '../lib/auth';
import { loadBoardSession, saveBoardSession } from '../lib/boardSession';
import { fetchConversation, saveConversation, type Conversation } from '../lib/conversations';
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
  const { dashboardId: routeDashboardId } = useParams();
  const navigate = useNavigate();

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
  const [dashboardsOpen, setDashboardsOpen] = useState(false);
  const [pendingUpload, setPendingUpload] = useState<File | null>(null);
  const [exporting, setExporting] = useState<ExportFormat | null>(null);
  const { notices, notify, notifyError, dismiss, dismissKey } = useNotices();

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

  // Which dataset the transcript currently in `messages` belongs to.
  //
  // Set only once a board's history has actually been established — restored
  // from the server, or started fresh on upload. Until then the save effect
  // stays out of the way: selecting a dataset renders with the new id beside the
  // *previous* board's messages for the tick before the fetch lands, and saving
  // that would overwrite the very history being fetched.
  //
  // State rather than a ref so the save effect re-runs when it is set. As a ref
  // it would have to be assigned before React flushed the restore's own state
  // updates, which happens to hold today and would break silently the first time
  // an await moved.
  const [hydratedDatasetId, setHydratedDatasetId] = useState<string | null>(null);

  const {
    dashboard,
    messages,
    threadId,
    isThinking,
    referencedWidgetId,
    saveStatus,
    saveError,
    canRetrySend,
    retryLastMessage,
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

  // Persist chat + dashboard link per dataset so the board can be restored.
  //
  // Two destinations, on purpose. The server copy is the real one — it is what
  // makes the history follow the dashboard onto another browser or machine.
  // `localStorage` stays as a fallback for when that write fails, so a backend
  // blip costs the user nothing they can see.
  useEffect(() => {
    const datasetId = dataset?.datasetId;
    if (!datasetId || hydratedDatasetId !== datasetId) return;

    if (!dashboard.dashboardId) return;

    saveBoardSession(dashboard.dashboardId, {
      dashboardId: dashboard.dashboardId,
      messages,
    });

    // Debounced because a single exchange moves `messages` several times — the
    // user's turn, then the reply — and each save rewrites every row.
    const timer = window.setTimeout(() => {
      void saveConversation(dashboard.dashboardId as string, messages, threadId).catch((err) => {
        // Deliberately quiet: the transcript is on screen and in localStorage
        // either way, and a toast here would interrupt a conversation to report
        // something the next message will retry anyway.
        console.warn('Failed to save chat history:', err);
      });
    }, 800);
    return () => window.clearTimeout(timer);
  }, [dataset?.datasetId, hydratedDatasetId, dashboard.dashboardId, messages, threadId]);

  useEffect(() => {
    if (!routeDashboardId) return;
    if (dashboard.dashboardId === routeDashboardId) return;

    let mounted = true;
    async function loadFromRoute() {
      try {
        const { getDashboard } = await import('../lib/dashboards');
        const dash = await getDashboard(routeDashboardId!);
        
        const { listDatasets } = await import('../lib/datasets');
        const { datasets } = await listDatasets();
        
        let foundDatasetId = null;
        if (dash.widgets.length > 0) {
          const { getChart } = await import('../lib/dashboards');
          const chart = await getChart(dash.widgets[0].chart_id);
          foundDatasetId = chart.dataset_id;
        }
        
        let foundDataset = null;
        if (foundDatasetId) {
           foundDataset = datasets.find((d) => d.dataset_id === foundDatasetId);
        }

        if (!mounted) return;

        if (foundDataset) {
          setDataset({
            datasetId: foundDataset.dataset_id,
            fileName: foundDataset.logical_name,
            rowCount: foundDataset.row_count,
            columnCount: foundDataset.column_count,
          });
        }
        
        const conversation = await restoreConversation(dash.id);
        await applyLoadedCanvas(
          dash,
          conversation.messages.length > 0 ? conversation.messages : undefined,
          conversation.threadId,
        );
        if (foundDataset) setHydratedDatasetId(foundDataset.dataset_id);
      } catch (err) {
        console.error("Failed to load dashboard from URL", err);
      }
    }
    loadFromRoute();
    return () => { mounted = false; };
  }, [routeDashboardId, dashboard.dashboardId]);

  /**
   * Autosave failures, said out loud.
   *
   * `saveError` was computed and returned by the hook and then read by nobody:
   * the only sign of a failed save was the Save button turning red, which told
   * the user something had gone wrong and nothing about what — and autosave
   * stops retrying on failure, so a board could sit unsaved indefinitely with
   * the reason known only to the code that threw it away.
   */
  useEffect(() => {
    if (saveStatus === 'error') {
      notify({
        key: 'save',
        kind: 'error',
        message: saveError
          ? `Could not save the dashboard. ${saveError}`
          : 'Could not save the dashboard.',
        action: { label: 'Try again', onClick: () => void saveNow() },
      });
    } else if (saveStatus === 'saved') {
      dismissKey('save');
    }
  }, [saveStatus, saveError, notify, dismissKey, saveNow]);

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
    restoredThreadId?: string | null,
  ) => {
    const loadedWidgets = await widgetsFromDashboard(selected);
    loadDashboardState(
      selected.id,
      selected.name,
      loadedWidgets,
      restoredMessages,
      restoredThreadId,
    );
  };

  /**
   * The transcript for a board being opened.
   *
   * The server holds it; `localStorage` is consulted only when that read fails
   * or comes back empty, which covers a board whose history predates the
   * conversations table. An empty result is a real answer — a board nobody has
   * chatted on — so it is returned as such rather than treated as a miss.
   */
  const restoreConversation = async (dashboardId: string): Promise<Conversation> => {
    try {
      const stored = await fetchConversation(dashboardId);
      if (stored.messages.length > 0) return stored;
    } catch (err) {
      console.warn('Failed to load chat history from server:', err);
    }
    const session = loadBoardSession(dashboardId);
    return { messages: session?.messages ?? [], threadId: null };
  };

  const handleLoadSavedDataset = async (entry: SavedDatasetEntry) => {
    const nextDatasetId = entry.dataset.dataset_id;
    try {
      if (dashboard.dashboardId && dataset?.datasetId && dataset.datasetId !== nextDatasetId) {
        await saveNow();
        saveBoardSession(dashboard.dashboardId, {
          dashboardId: dashboard.dashboardId,
          messages,
        });
        // Flush the outgoing board's chat before its messages are replaced —
        // the debounced save in the effect above would otherwise be cancelled
        // by this very switch and lose the last exchange.
        await saveConversation(dashboard.dashboardId, messages, threadId).catch((err) => {
          console.warn('Failed to save chat history:', err);
        });
        resetForDataset();
      }

      // Nothing may be written for this dataset until its own history is back.
      setHydratedDatasetId(null);

      setChartTypeFilter([]);
      setDataset({
        datasetId: nextDatasetId,
        fileName: entry.dataset.logical_name,
        rowCount: entry.dataset.row_count,
        columnCount: entry.dataset.column_count,
      });

      const title = defaultDashboardName(entry.dataset.logical_name);
      let activeDashboard = entry.dashboard;
      
      if (!activeDashboard) {
        const { createDashboard } = await import('../lib/dashboards');
        activeDashboard = await createDashboard(title);
      }

      const conversation = await restoreConversation(activeDashboard.id);

      await applyLoadedCanvas(
        activeDashboard,
        conversation.messages.length > 0 ? conversation.messages : undefined,
        conversation.threadId,
      );

      setHydratedDatasetId(nextDatasetId);
      openAiChat(setActiveItem, setChatOpen);
      if (activeDashboard.id !== routeDashboardId) {
        navigate(`/dashboard/${activeDashboard.id}`, { replace: true });
      }
    } catch (err) {
      notifyError(err, 'Could not open that dashboard.', {
        key: 'load-dashboard',
        onRetry: () => void handleLoadSavedDataset(entry),
      });
    }
  };

  const handleSidebarSelect = (id: SidebarItemId) => {
    if (id === 'settings') {
      setPasswordOpen(true);
      return;
    }
    if (id === 'data') {
      setBrowseOpen(true);
      return;
    }
    if (id === 'edit-data') {
      if (!dataset) {
        setBrowseOpen(true);
        return;
      }
      setActiveItem('edit-data');
      setChatOpen(false);
      return;
    }
    if (id === 'dashboards') {
      setDashboardsOpen(true);
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
      if (dashboard.dashboardId) {
        saveBoardSession(dashboard.dashboardId, {
          dashboardId: dashboard.dashboardId,
          messages,
        });
        await saveConversation(dashboard.dashboardId, messages, threadId).catch((err) => {
          console.warn('Failed to save chat history:', err);
        });
      }
      const result = await uploadDataset(file);
      const isSwitch = result.dataset_id !== dataset?.datasetId;
      if (isSwitch) {
        setHydratedDatasetId(null);
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
      if (isSwitch) {
        const { createDashboard } = await import('../lib/dashboards');
        const newDash = await createDashboard(boardName?.trim() || savedName);
        loadDashboardState(newDash.id, newDash.name, [], [], null);
      }
      setHydratedDatasetId(result.dataset_id);
      openAiChat(setActiveItem, setChatOpen);
      setBrowseOpen(false);
      setPendingUpload(null);
    } catch (err) {
      // Shown next to the upload control rather than in the notice stack: the
      // user is looking at the file picker, and that is where the answer to
      // "what happened to my file" belongs.
      setUploadError(errorMessage(err));
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
    await handleLoadSavedDataset({ 
      id: dashboard ? dashboard.id : selected.dataset_id, 
      dataset: selected, 
      dashboard, 
      chartCount 
    });
  };

  const handleExportDashboard = async (format: ExportFormat) => {
    const el = document.querySelector<HTMLElement>('.dashboard-canvas');
    if (!el) {
      notify({
        key: 'export',
        kind: 'validation',
        message: 'Open the dashboard canvas before exporting — the Data view cannot be exported.',
      });
      return;
    }

    const name = boardTitle(dashboard.dashboardName, dataset?.fileName);
    setExporting(format);
    notify({
      key: 'export',
      kind: 'working',
      message: format === 'pdf' ? 'Building the PDF…' : 'Rendering the image…',
    });
    try {
      const fileName = await exportDashboard(el, { format, name });
      notify({ key: 'export', kind: 'success', message: `Saved ${fileName} to your downloads.` });
    } catch (err) {
      // Rasterising a large canvas can run out of memory, and the encoders can
      // refuse — both worth retrying, and neither previously visible: this used
      // to be a console.error, so a failed export looked exactly like a
      // successful one that the browser had saved somewhere unnoticed.
      notifyError(err, 'Export failed.', {
        key: 'export',
        onRetry: () => void handleExportDashboard(format),
      });
    } finally {
      setExporting(null);
    }
  };

  const handleSendMessage = (text: string, chartType?: ChartType | null) => {
    void sendMessage(text, chartType);
  };

  // The type goes both ways on purpose: as a field the backend enforces against
  // the plan, and in the prompt, which is what lets the answer explain itself
  // when the data cannot support the pick and a substitute is drawn instead.
  const handleSetupAsk = (chartType: ChartType, question: string) => {
    handleSendMessage(buildChartPrompt(chartType, question), chartType);
  };

  const handleNewDashboard = async () => {
    // Was a window.confirm offering "save first?" — whose Cancel button
    // silently discarded the work, and which had no third option for "actually,
    // don't create one". The board autosaves on every other path, so asking
    // here was the anomaly: save, and only proceed if the work is safe.
    if (saveStatus === 'dirty' || saveStatus === 'error') {
      const saved = await saveNow();
      if (!saved) {
        // The save failure already raised its own notice with a retry; this
        // says why the new dashboard did not appear.
        notify({
          key: 'new-dashboard',
          kind: 'validation',
          message:
            'This dashboard has unsaved changes that could not be saved, so a new one was not created.',
        });
        return;
      }
    }

    if (!dataset) return;

    try {
      const { createDashboard } = await import('../lib/dashboards');
      const newDash = await createDashboard(dataset.fileName);
      loadDashboardState(newDash.id, newDash.name, [], [], null);
      openAiChat(setActiveItem, setChatOpen);
      navigate(`/dashboard/${newDash.id}`);
    } catch (err) {
      notifyError(err, 'Could not create a new dashboard.', {
        key: 'new-dashboard',
        onRetry: () => void handleNewDashboard(),
      });
    }
  };

  const showChat = chatOpen && activeItem === 'ai-chat';
  const showAdd = activeItem === 'add';
  const showSetup = activeItem === 'setup';
  const showFilter = activeItem === 'filter';
  const showDatasetSheet = activeItem === 'edit-data' && Boolean(dataset);

  return (
    <div className="board-app">
      <TopBar
        title={boardTitle(dashboard.dashboardName, dataset?.fileName)}
        sidebarCollapsed={sidebarCollapsed}
        userEmail={userEmail}
        username={username}
        onToggleSidebar={() => setSidebarCollapsed(!sidebarCollapsed)}
        onRename={() => setRenameOpen(true)}
        onExport={(format) => void handleExportDashboard(format)}
        exporting={exporting}
        onSave={() => saveNow()}
        saveStatus={saveStatus}
        saveError={saveError}
        shareDashboardId={dashboard.dashboardId}
        onNewDashboard={handleNewDashboard}
        onSetPassword={!hasPassword ? () => setPasswordOpen(true) : undefined}
        onOpenSettings={() => navigate('/settings#connections')}
        onLogout={onLogout}
        canExport={dashboard.widgets.length > 0}
      />

      <AccountPasswordModal
        open={passwordOpen}
        hasPassword={hasPassword}
        onClose={() => setPasswordOpen(false)}
        onSaved={() => setHasPassword(true)}
      />

      <div className="board-body">
        <NoticeStack notices={notices} onDismiss={dismiss} />

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
          canRetry={canRetrySend}
          onRetry={retryLastMessage}
        />

        {dashboardsOpen && (
          <DashboardsModal
            open={dashboardsOpen}
            currentDatasetId={dataset?.datasetId}
            currentDashboardId={dashboard.dashboardId}
            onClose={() => setDashboardsOpen(false)}
            onSelect={(entry) => void handleLoadSavedDataset(entry)}
          />
        )}

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
            onOpenStyle={(id) => {
              // Toggles, so the palette button that opened the panel also closes
              // it — the panel's own close button was removed with its header.
              setStyleWidgetId((current) => (current === id ? null : id));
            }}
            onReference={(id) => {
              referenceWidget(referencedWidgetId === id ? null : id);
              if (referencedWidgetId !== id) {
                openAiChat(setActiveItem, setChatOpen);
              }
            }}
            referencedWidgetId={referencedWidgetId}
            onDelete={(id) => {
              if (styleWidgetId === id) setStyleWidgetId(null);
              const title = dashboard.widgets.find((w) => w.id === id)?.title;
              const restore = deleteWidget(id);
              if (!restore) return;
              // Deleting a chart is a single unconfirmed click and autosave
              // commits it 1.5 s later. An undo is a better answer than a
              // confirmation: it costs nothing on the ordinary path, where the
              // user meant it.
              notify({
                key: 'delete-widget',
                kind: 'success',
                message: title ? `Removed “${title}”.` : 'Chart removed.',
                action: {
                  label: 'Undo',
                  onClick: () => {
                    restore();
                    dismissKey('delete-widget');
                  },
                },
              });
            }}
            onCsvSelected={handleCsvPicked}
            onOpenData={() => {
              if (dataset) {
                setActiveItem('edit-data');
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
              // Returned, not discarded: a rejected block leaves the chart
              // exactly as it was, so without this the control moves and
              // nothing happens anywhere.
              const error = await editWidgetStyle(styleWidget.id, { style });
              setStyleBusy(false);
              return error;
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
