import { useCallback, useRef, useState } from 'react';
import type { ChartWidget, ChatMessage, DashboardState } from '../types/dashboard';
import {
  analyze,
  answerClarification,
  isCleaningOptions,
  type AgentResponse,
} from '../lib/agent';

/** Used only when the backend somehow pauses without a question of its own. */
const FALLBACK_QUESTION: Record<string, string> = {
  clarification: 'Could you clarify your request?',
  cleaning_choice: 'How should I handle a data-quality issue in this dataset?',
  confirmation: 'Please confirm before I continue.',
};
import { widgetsFromAgent } from '../lib/chartWidgets';
import { ApiError } from '../lib/api';

const WELCOME =
  'Hi! Ask me a question about your dataset — for example “average price by category” or “how has revenue changed over time”. I run the query on your data and put the chart on the canvas.';

function uid(prefix: string) {
  return `${prefix}-${crypto.randomUUID().slice(0, 8)}`;
}

function errorText(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return 'Something went wrong talking to the server.';
}

export function useDashboard(datasetId: string | null) {
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

  const selectWidget = useCallback((id: string | null) => {
    setDashboard((prev) => ({ ...prev, selectedWidgetId: id }));
  }, []);

  const setDashboardMeta = useCallback((dashboardId: string, dashboardName: string) => {
    setDashboard((prev) => ({ ...prev, dashboardId, dashboardName }));
  }, []);

  const updateWidget = useCallback((id: string, patch: Partial<ChartWidget>) => {
    setDashboard((prev) => ({
      ...prev,
      widgets: prev.widgets.map((w) => (w.id === id ? { ...w, ...patch } : w)),
    }));
  }, []);

  const deleteWidget = useCallback((id: string) => {
    setDashboard((prev) => ({
      widgets: prev.widgets.filter((w) => w.id !== id),
      selectedWidgetId: prev.selectedWidgetId === id ? null : prev.selectedWidgetId,
    }));
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
      const created = widgetsFromAgent(res.charts ?? [], placedCount.current, () => uid('chart'));
      placedCount.current += created.length;

      pushAssistant({
        content: res.answer ?? 'Done.',
        // Link the reply to the first chart it produced, so "View on canvas"
        // has somewhere to go.
        chartId: created[0]?.id,
      });

      if (created.length === 0) return;
      setDashboard((prev) => ({
        widgets: [...prev.widgets, ...created],
        selectedWidgetId: created[0].id,
      }));
    },
    [pushAssistant],
  );

  const sendMessage = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      if (!datasetId) {
        pushAssistant({ content: 'Upload a CSV file first, then ask me about it.' });
        return;
      }

      setMessages((prev) => [
        ...prev,
        { id: uid('msg'), role: 'user', content: trimmed, timestamp: Date.now() },
      ]);
      setIsThinking(true);

      try {
        const res =
          awaitingAnswer.current && threadId.current
            ? await answerClarification(threadId.current, trimmed, pendingInterruptId.current)
            : await analyze(trimmed, datasetId, threadId.current);
        applyResponse(res);
      } catch (err) {
        // A paused run is left paused on transport failure, so a retry resumes
        // it rather than silently starting a fresh analysis.
        pushAssistant({ content: errorText(err) });
      } finally {
        setIsThinking(false);
      }
    },
    [datasetId, applyResponse, pushAssistant],
  );

  const loadDashboardState = useCallback(
    (dashboardId: string, dashboardName: string, widgets: ChartWidget[]) => {
      threadId.current = null;
      awaitingAnswer.current = false;
      pendingInterruptId.current = null;
      placedCount.current = widgets.length;
      setDashboard({
        widgets,
        selectedWidgetId: widgets.length > 0 ? widgets[0].id : null,
        dashboardId,
        dashboardName,
      });
      setMessages([
        { id: uid('msg'), role: 'assistant', content: `Loaded dashboard: ${dashboardName}`, timestamp: Date.now() },
      ]);
    },
    []
  );

  /** Drop canvas + conversation state when a different dataset is uploaded. */
  const resetForDataset = useCallback(() => {
    threadId.current = null;
    awaitingAnswer.current = false;
    pendingInterruptId.current = null;
    placedCount.current = 0;
    setDashboard({ widgets: [], selectedWidgetId: null, dashboardId: undefined, dashboardName: undefined });
    setMessages([{ id: uid('msg'), role: 'assistant', content: WELCOME, timestamp: Date.now() }]);
  }, []);

  return {
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
  };
}
