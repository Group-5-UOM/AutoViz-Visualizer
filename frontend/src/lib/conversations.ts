import { apiRequest } from './api';
import type { ChatMessage, ChatOption } from '../types/dashboard';

/**
 * The chat transcript, server-side.
 *
 * The canvas has always come back from the database; the conversation that
 * produced it used to live only in `localStorage`, so opening a board on a
 * second machine restored the charts under a blank chat panel. These two calls
 * are what close that gap — `boardSession` stays as an offline fallback.
 */

interface WireChatMessage {
  client_id: string | null;
  role: string;
  content: string;
  chart_id: string | null;
  referenced_title: string | null;
  options: ChatOption[] | null;
  timestamp_ms: number | null;
}

interface WireConversation {
  dashboard_id: string;
  thread_id: string | null;
  updated_at: string | null;
  messages: WireChatMessage[];
}

export interface Conversation {
  /** The agent thread, so a reopened board can refine charts instead of starting cold. */
  threadId: string | null;
  messages: ChatMessage[];
}

function newId(): string {
  return `msg-${crypto.randomUUID().slice(0, 8)}`;
}

function toChatMessage(m: WireChatMessage): ChatMessage {
  return {
    // The stored id when there is one, so React keys survive a reload. Rows
    // written before client_id existed get a fresh one rather than an empty key.
    id: m.client_id ?? newId(),
    role: m.role === 'user' ? 'user' : 'assistant',
    content: m.content,
    ...(m.chart_id ? { chartId: m.chart_id } : {}),
    ...(m.referenced_title ? { referencedTitle: m.referenced_title } : {}),
    ...(m.options?.length ? { options: m.options } : {}),
    timestamp: m.timestamp_ms ?? Date.now(),
  };
}

function toWire(m: ChatMessage): WireChatMessage {
  return {
    client_id: m.id,
    role: m.role,
    content: m.content,
    chart_id: m.chartId ?? null,
    referenced_title: m.referencedTitle ?? null,
    options: m.options ?? null,
    timestamp_ms: m.timestamp,
  };
}

export async function fetchConversation(dashboardId: string): Promise<Conversation> {
  const res = await apiRequest<WireConversation>(
    `/conversations/${encodeURIComponent(dashboardId)}`,
    { method: 'GET' },
  );
  return {
    threadId: res.thread_id,
    messages: (res.messages ?? []).map(toChatMessage),
  };
}

/**
 * Replace the stored transcript. The whole list goes every time: the client is
 * the only writer and holds all of it, so a full replace cannot drift the way a
 * partial append would after a retried save.
 *
 * A restored chart-attachment reference points at a chart title, and the chart
 * id is only meaningful to the canvas that is open — both ride along as display
 * text, which is why nothing here has to be resolved against the chart tables.
 */
export async function saveConversation(
  dashboardId: string,
  messages: ChatMessage[],
  threadId: string | null,
): Promise<void> {
  await apiRequest<WireConversation>(`/conversations/${encodeURIComponent(dashboardId)}`, {
    method: 'PUT',
    body: { messages: messages.map(toWire), thread_id: threadId },
  });
}
