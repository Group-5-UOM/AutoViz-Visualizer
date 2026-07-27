import { apiRequest } from './api';

export interface DatasetUploadResult {
  dataset_id: string;
  logical_name: string;
  row_count: number;
  column_count: number;
}

export async function uploadDataset(file: File): Promise<DatasetUploadResult> {
  const form = new FormData();
  form.append('file', file);
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
