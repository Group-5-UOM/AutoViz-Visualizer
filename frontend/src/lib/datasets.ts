import { apiRequest } from './api';

/** One table inside a file: a worksheet, or a block of a delimited file. */
export interface SheetInfo {
  name: string;
  index: number;
  kind: 'sheet' | 'block' | 'table';
  columns: string[];
  approx_rows: number | null;
  is_empty: boolean;
}

export interface InspectResult {
  sheets: SheetInfo[];
  /** False when the file holds one table and a picker would have one row. */
  needs_choice: boolean;
}

/**
 * Ask what tables are in a file, without importing any of them.
 *
 * Costs an extra send of the same bytes, which is why `shouldInspect` decides
 * when it is worth doing rather than this running on every upload.
 */
export async function inspectFile(file: File): Promise<InspectResult> {
  const form = new FormData();
  form.append('file', file);
  return apiRequest<InspectResult>('/datasets/inspect', { method: 'POST', form });
}

export interface DatasetUploadResult {
  dataset_id: string;
  logical_name: string;
  row_count: number;
  column_count: number;
  /** Present only when sheets were chosen; the first is the one above. */
  datasets?: { dataset_id: string; logical_name: string; sheet: string }[];
  /** Sheets asked for that could not be read. The rest still imported. */
  skipped?: { sheet: string; error: string }[];
}

/**
 * Upload a file, optionally importing only the named tables inside it.
 *
 * Each sheet becomes a dataset of its own. Omitting `sheets` reads the file as
 * a single table, which is what every caller did before sheets existed.
 */
export async function uploadDataset(file: File, sheets?: string[]): Promise<DatasetUploadResult> {
  const form = new FormData();
  form.append('file', file);
  // JSON rather than a joined string: "Revenue, net" is an ordinary sheet name.
  if (sheets?.length) form.append('sheets', JSON.stringify(sheets));
  return apiRequest<DatasetUploadResult>('/datasets/upload', {
    method: 'POST',
    form,
  });
}

export interface DatasetMetadata {
  dataset_id: string;
  logical_name: string;
  row_count: number;
  column_count: number;
  created_at: string;
}

export async function listDatasets(): Promise<{ datasets: DatasetMetadata[] }> {
  return apiRequest<{ datasets: DatasetMetadata[] }>('/datasets', {
    method: 'GET',
  });
}

export async function deleteDataset(datasetId: string): Promise<{ removed: boolean; dataset_id: string }> {
  return apiRequest<{ removed: boolean; dataset_id: string }>(`/datasets/${datasetId}`, {
    method: 'DELETE',
  });
}

export interface DatasetPreviewResult {
  rows: Record<string, unknown>[];
}

export async function previewDataset(datasetId: string, limit: number = 10): Promise<DatasetPreviewResult> {
  return apiRequest<DatasetPreviewResult>(`/datasets/${datasetId}/preview?limit=${limit}`, {
    method: 'GET',
  });
}

export interface DatasetColumn {
  name: string;
  type: string;
}

export async function fetchDatasetSchema(datasetId: string) {
  return apiRequest<{ columns: DatasetColumn[] }>(`/datasets/${datasetId}/schema`, {
    method: 'GET',
  });
}
