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
