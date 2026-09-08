import { apiRequest } from './api';

/**
 * Client for the deterministic analysis routes. Used when the user edits the
 * analysis_plan JSON directly and re-runs without calling the LLM.
 */

export interface ValidatePlanResult {
  valid: boolean;
  errors?: string[];
  repaired_plan?: Record<string, unknown>;
  error?: string;
  error_code?: string;
}

export interface PipelineResult {
  status: 'ok' | 'error' | 'confirmation_required' | string;
  result?: {
    result_table?: Record<string, unknown>[];
    row_count?: number;
  } | null;
  chart_spec?: { type?: string; x?: string; y?: string } | null;
  vega_lite_spec?: Record<string, unknown> | null;
  warnings?: string[];
  errors?: string[];
  error?: string;
  error_code?: string;
  failed_step?: string;
}

export async function validatePlan(
  datasetId: string,
  analysisPlan: Record<string, unknown>,
): Promise<ValidatePlanResult> {
  return apiRequest<ValidatePlanResult>('/analysis/validate', {
    method: 'POST',
    body: { dataset_id: datasetId, analysis_plan: analysisPlan },
  });
}

export async function runPipeline(
  datasetId: string,
  analysisPlan: Record<string, unknown>,
  approvedPreprocessingHash?: string | null,
): Promise<PipelineResult> {
  return apiRequest<PipelineResult>('/analysis/pipeline', {
    method: 'POST',
    body: {
      dataset_id: datasetId,
      analysis_plan: analysisPlan,
      ...(approvedPreprocessingHash
        ? { approved_preprocessing_hash: approvedPreprocessingHash }
        : {}),
    },
  });
}
