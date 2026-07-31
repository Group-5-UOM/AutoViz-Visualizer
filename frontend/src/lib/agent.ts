import { apiRequest } from './api';

/**
 * Client for the agentic routes (`POST /agent/analyze`, `POST /agent/answer`).
 *
 * The backend always answers 200 with a structured envelope and carries the
 * workflow outcome in `status`, so a "failed" run is a normal response body —
 * not a thrown ApiError. Only transport/auth problems throw.
 */

/** One planner sub-task, executed and charted. Mirrors agent.state.ChartResult. */
export interface AgentChartResult {
  task: string;
  /**
   * The agent's stable identity for this chart. A refinement returns the id of
   * the chart it changed, which is what lets the canvas update that card instead
   * of putting a near-duplicate next to it.
   */
  chart_id?: string;
  status: 'ok' | 'partial' | 'error';
  result?: {
    result_table?: Record<string, unknown>[];
    row_count?: number;
  } | null;
  chart_spec?: { type?: string; x?: string; y?: string } | null;
  vega_lite_spec?: Record<string, unknown> | null;
  warnings?: string[];
  errors?: string[];
}

export interface AgentCompleted {
  status: 'completed';
  answer: string | null;
  charts: AgentChartResult[];
  thread_id: string;
}

export interface AgentFailed {
  status: 'failed';
  answer?: string | null;
  errors?: string[];
  charts?: AgentChartResult[];
  thread_id: string;
}

/**
 * One answer to a cleaning question, written for someone who does not know the
 * technique. `label` is the offer, `detail` is what it costs in this dataset's
 * real row counts, and `technique` is the jargon — kept separate so it can go
 * behind a "how this works" disclosure rather than lead.
 */
export interface CleaningOption {
  label: string;
  detail: string;
  technique: string;
  recommended: boolean;
}

/** What the cleaning question is about, so the counts can be shown alongside it. */
export interface QualityIssue {
  kind: string;
  column: string | null;
  affected: number;
  fraction: number;
  detail?: Record<string, unknown>;
}

/**
 * The run paused. `pause_kind` says which decision the user is making:
 *
 * - `clarification`   — the request was ambiguous.
 * - `cleaning_choice` — a data-quality problem needs a decision before the
 *                       numbers are computed. `options` are `CleaningOption`s,
 *                       one flagged `recommended` so it can be preselected.
 * - `confirmation`    — approving a cleaning step that would drop a large share
 *                       of rows. `options` are plain strings.
 *
 * `options` is therefore either shape; narrow on `pause_kind` before rendering.
 */
export interface AgentWaiting {
  status: 'waiting_for_user';
  question: string | null;
  options: string[] | CleaningOption[];
  pause_kind: 'clarification' | 'cleaning_choice' | 'confirmation';
  preprocessing_hash?: string;
  impact?: { dropped?: number; input_rows?: number };
  /** cleaning_choice only: which finding is being decided. */
  slot?: string;
  issue?: QualityIssue;
  /**
   * Which decision this is. Parallel workers can pause on several at once, so
   * only one is presented at a time: `pending_count` is how many are queued
   * (this one included) and `interrupt_id` must be sent back with the answer so
   * it reaches the workers that asked it rather than whichever paused first.
   */
  interrupt_id?: string;
  pending_count?: number;
  /** The answered decision was already resolved; nothing was consumed. */
  stale_answer?: boolean;
  thread_id: string;
}

/** Type guard: cleaning options are objects, clarification/confirmation are strings. */
export function isCleaningOptions(
  waiting: AgentWaiting,
): waiting is AgentWaiting & { options: CleaningOption[] } {
  return waiting.pause_kind === 'cleaning_choice';
}

/**
 * The answer to send back for a chosen option. The backend matches on the label
 * and falls back to leaving the data alone when it cannot read the reply, so the
 * label must be sent verbatim.
 */
export function answerFor(option: CleaningOption): string {
  return option.label;
}

export type AgentResponse = AgentCompleted | AgentFailed | AgentWaiting;

export async function analyze(
  request: string,
  datasetId: string,
  threadId?: string | null,
): Promise<AgentResponse> {
  return apiRequest<AgentResponse>('/agent/analyze', {
    method: 'POST',
    body: {
      request,
      dataset_id: datasetId,
      ...(threadId ? { thread_id: threadId } : {}),
    },
  });
}

/**
 * Resume a run paused on a clarification, a cleaning choice or a preprocessing
 * confirmation. Pass the `interrupt_id` from the pause being answered; omitting
 * it answers whichever decision is currently at the head of the queue.
 */
export async function answerClarification(
  threadId: string,
  answer: string,
  interruptId?: string | null,
): Promise<AgentResponse> {
  return apiRequest<AgentResponse>('/agent/answer', {
    method: 'POST',
    body: {
      thread_id: threadId,
      answer,
      ...(interruptId ? { interrupt_id: interruptId } : {}),
    },
  });
}
