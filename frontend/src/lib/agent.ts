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
 * The run paused. `pause_kind` says which decision the user is making:
 * "clarification" (an ambiguous request) or "confirmation" (approving a
 * preprocessing step that would drop a large number of rows).
 */
export interface AgentWaiting {
  status: 'waiting_for_user';
  question: string | null;
  options: string[];
  pause_kind: 'clarification' | 'confirmation';
  preprocessing_hash?: string;
  impact?: { dropped?: number; input_rows?: number };
  thread_id: string;
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

/** Resume a run paused on a clarification or a preprocessing confirmation. */
export async function answerClarification(
  threadId: string,
  answer: string,
): Promise<AgentResponse> {
  return apiRequest<AgentResponse>('/agent/answer', {
    method: 'POST',
    body: { thread_id: threadId, answer },
  });
}
