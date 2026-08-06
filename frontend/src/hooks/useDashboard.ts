import { useCallback, useEffect, useRef, useState } from 'react';
import type {
  ChartStyle,
  ChartType,
  ChartWidget,
  ChatMessage,
  DashboardState,
  SaveStatus,
} from '../types/dashboard';
import { styleChart } from '../lib/chartStyle';
import {
  analyze,
  answerClarification,
  isCleaningOptions,
  type AgentResponse,
} from '../lib/agent';
import { defaultDashboardName, persistSignature, syncDashboard } from '../lib/dashboardSync';

/** Used only when the backend somehow pauses without a question of its own. */
const FALLBACK_QUESTION: Record<string, string> = {
  clarification: 'Could you clarify your request?',
  cleaning_choice: 'How should I handle a data-quality issue in this dataset?',
  confirmation: 'Please confirm before I continue.',
};
import { applyAgentCharts } from '../lib/chartWidgets';
import { ApiError } from '../lib/api';

const WELCOME =
  'Hi! Ask me a question about your dataset — for example “average price by category” or “how has revenue changed over time”. I run the query on your data and put the chart on the canvas.';

/**
 * How long the canvas has to sit still before it is saved. Dragging a chart
 * fires `onMove` on every pointer frame, so without this a single drag across
 * the canvas would be a hundred PUTs.
 */
const AUTOSAVE_DELAY_MS = 1500;

function uid(prefix: string) {
  return `${prefix}-${crypto.randomUUID().slice(0, 8)}`;
}

function errorText(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return 'Something went wrong talking to the server.';
}

export function useDashboard(datasetId: string | null, datasetFileName?: string | null) {
  const [dashboard, setDashboard] = useState<DashboardState>({
    widgets: [],
    selectedWidgetId: null,
  });
  const [messages, setMessages] = useState<ChatMessage[]>([
    { id: uid('msg'), role: 'assistant', content: WELCOME, timestamp: Date.now() },
  ]);
  const [isThinking, setIsThinking] = useState(false);

  // Conversation continuity: the backend keys refinements ("make it a bar
  // chart") and paused clarification runs off thread_id.
  const threadId = useRef<string | null>(null);
  // Set while a run is paused on a question — the next message resumes that run
  // via /agent/answer instead of starting a new analysis.
  const awaitingAnswer = useRef(false);
  // Which paused decision the question on screen belongs to. Parallel workers
  // can pause on several at once, so the answer has to name the one it is for
  // rather than landing on whichever the backend happens to reach first.
  const pendingInterruptId = useRef<string | null>(null);
  // Monotonic slot counter for canvas placement. It deliberately does not
  // decrease when a widget is deleted, so a new chart lands in a free slot
  // rather than on top of one the user kept.
  const placedCount = useRef(0);

  // A chart the user attached to the next message. Held here rather than in the
  // composer because the attach gesture happens on the canvas, and because
  // sending is what consumes it.
  const [referencedWidgetId, setReferencedWidgetId] = useState<string | null>(null);

  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const [lastSavedAt, setLastSavedAt] = useState<number | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  // The signature of what the server is known to hold. Everything else about
  // autosave follows from comparing this to the canvas.
  const baseline = useRef<string | null>(null);
  // Checked synchronously before the first await: two overlapping first saves
  // would each POST /dashboards and leave the user with a duplicate board.
  const inFlight = useRef(false);
  const saveTimer = useRef<number | null>(null);
  // A failed save stops the timer rather than retrying forever against a
  // backend that is down. Pressing Save clears it.
  const retryBlocked = useRef(false);
  // Read by the debounce callback, which fires long after the render that
  // scheduled it and must save what is on the canvas now.
  const dashboardRef = useRef(dashboard);
  const datasetRef = useRef({ id: datasetId, fileName: datasetFileName });

  const selectWidget = useCallback((id: string | null) => {
    setDashboard((prev) => ({ ...prev, selectedWidgetId: id }));
  }, []);

  const updateWidget = useCallback((id: string, patch: Partial<ChartWidget>) => {
    setDashboard((prev) => ({
      ...prev,
      widgets: prev.widgets.map((w) => (w.id === id ? { ...w, ...patch } : w)),
    }));
  }, []);

  /**
   * Restyle one chart where it sits.
   *
   * Presentation only, so nothing here goes near the agent thread: the spec's
   * numbers are the ones already executed and the request never re-runs a query.
   * `request` is the natural-language path ("make the bars orange"); `style` is
   * the panel's, which skips the model.
   *
   * Resolves to an error message when the request could not be applied, so the
   * caller can show it next to the control the user actually used. The chart is
   * left untouched in that case.
   */
  const editWidgetStyle = useCallback(
    async (id: string, edit: { request?: string; style?: ChartStyle }): Promise<string | null> => {
      const widget = dashboardRef.current.widgets.find((w) => w.id === id);
      if (!widget) return null;
      try {
        const res = await styleChart(
          widget.vegaLiteSpec,
          // The whole current block, not a diff — the backend merges onto it.
          edit.style ?? widget.style,
          edit.request,
        );
        setDashboard((prev) => ({
          ...prev,
          widgets: prev.widgets.map((w) =>
            w.id === id
              ? {
                  ...w,
                  vegaLiteSpec: res.vega_lite_spec,
                  style: res.style,
                  // Autosave cannot see inside the spec, so this is what tells
                  // it the chart needs writing back. Counted off `prev` rather
                  // than off the widget read before the request: two colour
                  // clicks in quick succession would otherwise both compute
                  // version 1, and the second edit would never be saved.
                  specVersion: (w.specVersion ?? 0) + 1,
                }
              : w,
          ),
        }));
        return null;
      } catch (err) {
        return errorText(err);
      }
    },
    [],
  );

  const deleteWidget = useCallback((id: string) => {
    setDashboard((prev) => ({
      widgets: prev.widgets.filter((w) => w.id !== id),
      selectedWidgetId: prev.selectedWidgetId === id ? null : prev.selectedWidgetId,
    }));
    // An attachment pointing at a chart that no longer exists would send a
    // chart_id the backend cannot resolve, and quietly behave as if unattached.
    setReferencedWidgetId((prev) => (prev === id ? null : prev));
  }, []);

  const pushAssistant = useCallback((message: Omit<ChatMessage, 'id' | 'role' | 'timestamp'>) => {
    setMessages((prev) => [
      ...prev,
      { ...message, id: uid('msg'), role: 'assistant', timestamp: Date.now() },
    ]);
  }, []);

  /** Turn one agent envelope into chat messages and (on success) canvas widgets. */
  const applyResponse = useCallback(
    (res: AgentResponse) => {
      threadId.current = res.thread_id ?? threadId.current;

      if (res.status === 'waiting_for_user') {
        awaitingAnswer.current = true;
        pendingInterruptId.current = res.interrupt_id ?? null;
        const question = res.question ?? FALLBACK_QUESTION[res.pause_kind];
        // Several independent decisions are queued: say so, or answering the
        // first one looks like the run stalled when the next question appears.
        const position =
          res.pending_count && res.pending_count > 1 ? `(1 of ${res.pending_count}) ` : '';
        pushAssistant({
          content: `${position}${question}`,
          // A cleaning choice arrives as objects carrying the row counts and the
          // recommendation; the other two pauses are plain strings. Normalising
          // here keeps the chat component with one shape to render.
          options: isCleaningOptions(res)
            ? res.options.map((o) => ({
                label: o.label,
                detail: o.detail,
                technique: o.technique,
                recommended: o.recommended,
              }))
            : ((res.options ?? []) as string[]).map((label) => ({ label })),
        });
        return;
      }

      awaitingAnswer.current = false;
      pendingInterruptId.current = null;

      if (res.status === 'failed') {
        const detail = res.errors?.length
          ? res.errors.join(' ')
          : (res.answer ?? 'The request could not be processed.');
        pushAssistant({ content: `I couldn't complete that. ${detail}` });
        return;
      }

      // Built outside the state updater: updaters must stay pure (StrictMode
      // invokes them twice, which would post every reply to the chat twice).
      // Read off the mirror ref for the same reason — the updater cannot be the
      // place that decides which widgets a refinement replaces.
      const applied = applyAgentCharts(
        dashboardRef.current.widgets,
        res.charts ?? [],
        placedCount.current,
        () => uid('chart'),
      );
      placedCount.current += applied.placed;

      pushAssistant({
        content: res.answer ?? 'Done.',
        // Link the reply to the first chart it produced, so "View on canvas"
        // has somewhere to go — including when that chart was one already there.
        chartId: applied.focusId ?? undefined,
      });

      if (applied.focusId === null) return;
      setDashboard((prev) => ({
        ...prev,
        widgets: applied.widgets,
        selectedWidgetId: applied.focusId,
      }));
    },
    [pushAssistant],
  );

  const sendMessage = useCallback(
    // `chartType` is set only when the user picked a type from a list rather
    // than describing one, so it is an argument and not hook state: a pick
    // belongs to the one message it was made for.
    async (text: string, chartType?: ChartType | null) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      if (!datasetId) {
        pushAssistant({ content: 'Upload a CSV file first, then ask me about it.' });
        return;
      }

      // Resolved before the message is posted so the transcript records what was
      // attached, and consumed on send: an attachment that outlived its message
      // would silently redirect the next, unrelated question onto that chart.
      const referenced = referencedWidgetId
        ? dashboardRef.current.widgets.find((w) => w.id === referencedWidgetId)
        : undefined;
      setReferencedWidgetId(null);

      setMessages((prev) => [
        ...prev,
        {
          id: uid('msg'),
          role: 'user',
          content: trimmed,
          referencedTitle: referenced?.title,
          timestamp: Date.now(),
        },
      ]);
      setIsThinking(true);

      try {
        const res =
          awaitingAnswer.current && threadId.current
            ? // A paused run is answering its own question; neither an attachment
              // nor a chart-type pick has anything to do with that decision.
              await answerClarification(threadId.current, trimmed, pendingInterruptId.current)
            : await analyze(
                trimmed,
                datasetId,
                threadId.current,
                referenced?.agentChartId,
                chartType,
              );
        applyResponse(res);
      } catch (err) {
        // A paused run is left paused on transport failure, so a retry resumes
        // it rather than silently starting a fresh analysis.
        pushAssistant({ content: errorText(err) });
      } finally {
        setIsThinking(false);
      }
    },
    [datasetId, applyResponse, pushAssistant, referencedWidgetId],
  );

  // --- persistence ----------------------------------------------------------

  const cancelPendingSave = useCallback(() => {
    if (saveTimer.current !== null) {
      window.clearTimeout(saveTimer.current);
      saveTimer.current = null;
    }
  }, []);

  /**
   * One pass at pushing the canvas to the server.
   *
   * `nameOverride` exists for the rename path: `setDashboard` has not flushed
   * by the time this runs, so the new name has to be handed over rather than
   * read back off the mirror ref.
   */
  const runSave = useCallback(async (nameOverride?: string) => {
    // A save is already going. The scheduler re-checks when it lands, so
    // dropping this attempt loses nothing and never doubles up a request.
    if (inFlight.current) return;

    const live = dashboardRef.current;
    const snapshot: DashboardState = nameOverride
      ? { ...live, dashboardName: nameOverride, nameIsAuto: false }
      : live;
    // An untouched canvas is not worth a dashboard row.
    if (snapshot.widgets.length === 0 && !snapshot.dashboardId) return;

    // Captured before the await so that edits made while the request is in
    // flight stay dirty: the baseline may only claim what was actually sent.
    const sent = persistSignature(snapshot);
    const wasNew = !snapshot.dashboardId;
    const { id, fileName } = datasetRef.current;

    inFlight.current = true;
    setSaveStatus('saving');
    setSaveError(null);
    try {
      const result = await syncDashboard(snapshot, id, defaultDashboardName(fileName));
      baseline.current = sent;
      retryBlocked.current = false;
      setDashboard((prev) => ({
        ...prev,
        dashboardId: result.dashboardId,
        dashboardName: result.name,
        nameIsAuto: prev.nameIsAuto ?? wasNew,
        widgets: prev.widgets.map((w) => {
          const chartId = result.newChartIds[w.id];
          const synced = result.syncedSpecVersions[w.id];
          if (chartId === undefined && synced === undefined) return w;
          return {
            ...w,
            ...(chartId ? { backendChartId: chartId } : {}),
            // What the server now holds. An edit made while the request was in
            // flight has already bumped specVersion past this, so it stays
            // dirty rather than being declared saved.
            ...(synced === undefined ? {} : { syncedSpecVersion: synced }),
          };
        }),
      }));
      setLastSavedAt(Date.now());
      setSaveStatus('saved');
    } catch (err) {
      // The baseline is left stale on purpose — the change really is unsaved,
      // so Retry re-sends it instead of declaring victory over it.
      retryBlocked.current = true;
      setSaveError(errorText(err));
      setSaveStatus('error');
    } finally {
      inFlight.current = false;
    }
  }, []);

  /**
   * Autosave scheduler — the single place that decides "the canvas differs
   * from what the server has".
   *
   * `saveStatus` is a dependency because this has to re-decide when a save
   * lands, not only when the canvas changes: an edit made mid-save is skipped
   * below, and the status settling back is what brings it round again.
   */
  useEffect(() => {
    dashboardRef.current = dashboard;
    datasetRef.current = { id: datasetId, fileName: datasetFileName };

    const nothingToSave = dashboard.widgets.length === 0 && !dashboard.dashboardId;
    if (nothingToSave || persistSignature(dashboard) === baseline.current) return;

    setSaveStatus((prev) => (prev === 'idle' || prev === 'saved' ? 'dirty' : prev));
    // A save in flight comes back through here when it finishes. A failed one
    // waits for the user instead of hammering a backend that is down every
    // couple of seconds.
    if (inFlight.current || retryBlocked.current) return;

    cancelPendingSave();
    saveTimer.current = window.setTimeout(() => {
      saveTimer.current = null;
      void runSave();
    }, AUTOSAVE_DELAY_MS);
  }, [dashboard, datasetId, datasetFileName, saveStatus, cancelPendingSave, runSave]);

  useEffect(() => cancelPendingSave, [cancelPendingSave]);

  useEffect(() => {
    if (saveStatus !== 'dirty' && saveStatus !== 'saving' && saveStatus !== 'error') return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [saveStatus]);

  /** Flush now — the Save button, and anything about to replace the canvas. */
  const saveNow = useCallback(
    async (nameOverride?: string) => {
      cancelPendingSave();
      retryBlocked.current = false;
      await runSave(nameOverride);
    },
    [cancelPendingSave, runSave],
  );

  /** Name the dashboard and persist it straight away. */
  const renameDashboard = useCallback(
    (name: string) => {
      const trimmed = name.trim();
      if (!trimmed) return;
      setDashboard((prev) => ({ ...prev, dashboardName: trimmed, nameIsAuto: false }));
      void saveNow(trimmed);
    },
    [saveNow],
  );

  const loadDashboardState = useCallback(
    (
      dashboardId: string,
      dashboardName: string,
      widgets: ChartWidget[],
      restoredMessages?: ChatMessage[],
    ) => {
      cancelPendingSave();
      threadId.current = null;
      awaitingAnswer.current = false;
      pendingInterruptId.current = null;
      placedCount.current = widgets.length;
      const next: DashboardState = {
        widgets,
        selectedWidgetId: widgets.length > 0 ? widgets[0].id : null,
        dashboardId,
        dashboardName,
        nameIsAuto: false,
      };
      // This is, by definition, exactly what the server holds. Without seeding
      // the baseline, opening a dashboard would immediately save it back.
      baseline.current = persistSignature(next);
      dashboardRef.current = next;
      retryBlocked.current = false;
      setDashboard(next);
      setSaveStatus('saved');
      setSaveError(null);
      setLastSavedAt(null);
      setMessages(
        restoredMessages && restoredMessages.length > 0
          ? restoredMessages
          : [
              {
                id: uid('msg'),
                role: 'assistant',
                content: `Loaded dashboard: ${dashboardName}`,
                timestamp: Date.now(),
              },
            ],
      );
    },
    [cancelPendingSave],
  );

  const replaceMessages = useCallback((next: ChatMessage[]) => {
    setMessages(next);
  }, []);

  /** Drop canvas + conversation state when a different dataset is uploaded. */
  const resetForDataset = useCallback(() => {
    cancelPendingSave();
    threadId.current = null;
    awaitingAnswer.current = false;
    pendingInterruptId.current = null;
    placedCount.current = 0;
    const next: DashboardState = { widgets: [], selectedWidgetId: null };
    baseline.current = persistSignature(next);
    dashboardRef.current = next;
    retryBlocked.current = false;
    setDashboard(next);
    setSaveStatus('idle');
    setSaveError(null);
    setLastSavedAt(null);
    setMessages([{ id: uid('msg'), role: 'assistant', content: WELCOME, timestamp: Date.now() }]);
  }, [cancelPendingSave]);

  return {
    dashboard,
    messages,
    isThinking,
    saveStatus,
    lastSavedAt,
    saveError,
    referencedWidgetId,
    referenceWidget: setReferencedWidgetId,
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
  };
}
