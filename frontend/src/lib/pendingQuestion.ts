/**
 * Whether the next message answers the question on screen, or asks a new one.
 *
 * While a run is paused, every message used to go to `/agent/answer`. So a user
 * who moved on — typed a new question, used the Setup panel, attached a chart —
 * had that request swallowed as the reply to a stale question: a cleaning
 * choice read "Create a Scatter chart…" as its answer, resolved it to "leave it
 * alone", and the paused forecast the user had already cancelled came back as
 * a chart in place of the scatter they asked for.
 */

/** The decision a paused run is waiting on, as far as routing needs to know. */
export interface PendingPause {
  /** `clarification` | `cleaning_choice` | `confirmation` */
  kind: string;
  /** Labels of the offered answers; the reply the backend matches on. */
  options: string[];
}

export interface OutgoingMessage {
  text: string;
  chartType?: string | null;
  agentChartId?: string;
}

const norm = (s: string) => s.trim().replace(/\s+/g, ' ').toLowerCase();

export function answersPendingQuestion(
  message: OutgoingMessage,
  pause: PendingPause | null,
): boolean {
  // A chart-type pick or an attached chart is a request about a chart. Neither
  // has anything to do with the decision being asked, which is why the old path
  // dropped both on the floor when it sent the text as an answer.
  if (message.chartType || message.agentChartId) return false;
  if (!pause) return true;
  // A clarification takes free text ("by revenue") — that is the point of
  // asking in words — so anything typed is still the reply.
  if (pause.kind === 'clarification' || pause.options.length === 0) return true;
  // A cleaning choice or a confirmation only understands its own options. Any
  // other reply would be bound to "do nothing", silently, so it is a new request.
  const said = norm(message.text);
  return pause.options.some((option) => norm(option) === said);
}
