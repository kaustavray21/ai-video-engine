/* ── Types for AI Video Engine Dashboard V2 ── */

export interface HeaderItem {
  key: string;
  value: string;
}

export interface ApiCallLog {
  id: number;
  method: string;
  endpoint: string;
  request_body: string;
  response_body: string;
  status_code: number;
  status_text: string;
  latency_ms: number;
  saved: boolean;
  created_at: string;
}

export interface DashboardStats {
  total_api_calls: number;
  total_videos: number;
  processed_videos: number;
  chart_data: { date: string; count: number }[];
}

export interface HistoryEntry {
  id: number;
  date: string;
  isoDate: string;
  method: string;
  url: string;
  requestBody: string;
  responseBody: string;
  status: string;
  statusCode: number | string;
}

export interface StudyMaterial {
  id: number;
  name: string;
  description: string;
  file_path: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  files_count: number;
  vectorstore_location: string;
  created_at: string;
  attached_courses_count: number;
}

export interface Course {
  id: number;
  title: string;
}
