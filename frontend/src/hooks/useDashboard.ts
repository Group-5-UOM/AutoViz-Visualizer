import { useCallback, useState } from 'react';
import type { ChartWidget, ChatMessage, DashboardState } from '../types/dashboard';
import { assistantReplyForChart, createMockChartFromPrompt } from '../lib/mockCharts';

function uid(prefix: string) {
  return `${prefix}-${crypto.randomUUID().slice(0, 8)}`;
}

export function useDashboard() {
  const [dashboard, setDashboard] = useState<DashboardState>({
    widgets: [],
    selectedWidgetId: null,
  });
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: uid('msg'),
      role: 'assistant',
      content:
        'Hi! Ask me to visualize your data — for example “show sales by category” or “trend of revenue over time”. Charts will appear on the canvas.',
      timestamp: Date.now(),
    },
  ]);
  const [isThinking, setIsThinking] = useState(false);

  const selectWidget = useCallback((id: string | null) => {
    setDashboard((prev) => ({ ...prev, selectedWidgetId: id }));
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

  const sendMessage = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;

    const userMsg: ChatMessage = {
      id: uid('msg'),
      role: 'user',
      content: trimmed,
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsThinking(true);

    await new Promise((r) => setTimeout(r, 650));

    setDashboard((prev) => {
      const chart = createMockChartFromPrompt(trimmed, prev.widgets.length);
      const widget: ChartWidget = { ...chart, id: uid('chart') };

      const assistantMsg: ChatMessage = {
        id: uid('msg'),
        role: 'assistant',
        content: assistantReplyForChart(widget.title),
        chartId: widget.id,
        timestamp: Date.now(),
      };
      setMessages((msgs) => [...msgs, assistantMsg]);
      setIsThinking(false);

      return {
        widgets: [...prev.widgets, widget],
        selectedWidgetId: widget.id,
      };
    });
  }, []);

  return {
    dashboard,
    messages,
    isThinking,
    selectWidget,
    updateWidget,
    deleteWidget,
    sendMessage,
  };
}
