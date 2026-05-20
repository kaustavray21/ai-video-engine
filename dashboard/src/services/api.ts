/* ── API service layer V2 ── */

import type { ApiCallLog, DashboardStats, StudyMaterial, Course } from '../types';

const BASE = '/api';

export async function sendRequest(
  endpoint: string,
  method: string = 'POST',
  body?: string | FormData,
  headers?: Record<string, string>,
): Promise<{ data: unknown; status: number; statusText: string; latencyMs: number }> {
  const url = endpoint.startsWith('http') || endpoint.startsWith(BASE) ? endpoint : `${BASE}${endpoint}`;
  const start = performance.now();

  try {
    const opts: RequestInit = {
      method,
      headers: headers ?? {},
    };
    
    // Add default Content-Type if not provided and body is not FormData
    const optsHeaders = opts.headers as Record<string, string>;
    if (!optsHeaders['Content-Type'] && !(body instanceof FormData)) {
      optsHeaders['Content-Type'] = 'application/json';
    }

    if (body && method !== 'GET' && method !== 'HEAD') {
      opts.body = body;
    }

    const res = await fetch(url, opts);
    const latencyMs = Math.round(performance.now() - start);

    const ct = res.headers.get('content-type');
    let data: unknown;
    if (ct && ct.includes('application/json')) {
      data = await res.json();
    } else {
      data = await res.text();
    }

    return { data, status: res.status, statusText: res.statusText || (res.ok ? 'OK' : 'Error'), latencyMs };
  } catch (err) {
    return {
      data: (err as Error).message,
      status: 0,
      statusText: 'Network Error',
      latencyMs: Math.round(performance.now() - start),
    };
  }
}

export async function logApiCall(payload: {
  method: string;
  endpoint: string;
  request_body: string;
  response_body: string;
  status_code: number;
  status_text: string;
  latency_ms: number;
}): Promise<{ id: number } | null> {
  try {
    const res = await fetch(`${BASE}/dashboard/log/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (res.ok) return await res.json();
  } catch { /* silent */ }
  return null;
}

export async function fetchLogs(params: {
  date?: string;
  saved_only?: boolean;
  limit?: number;
}): Promise<{ count: number; logs: ApiCallLog[] }> {
  try {
    const res = await fetch(`${BASE}/dashboard/logs/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    });
    if (res.ok) return await res.json();
  } catch { /* silent */ }
  return { count: 0, logs: [] };
}

export async function saveLogEntry(id: number): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/dashboard/logs/save/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id }),
    });
    return res.ok;
  } catch { return false; }
}

export async function fetchDashboardStats(): Promise<DashboardStats> {
  try {
    const res = await fetch(`${BASE}/dashboard/stats/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    if (res.ok) return await res.json();
  } catch { /* silent */ }
  return { total_api_calls: 0, total_videos: 0, processed_videos: 0, chart_data: [] };
}

// ── Study Materials ──

export async function uploadStudyMaterial(
  name: string,
  zipFile: File,
  description?: string,
): Promise<{ id: number; name: string; status: string } | null> {
  try {
    const formData = new FormData();
    formData.append('name', name);
    formData.append('zip_file', zipFile);
    if (description) formData.append('description', description);

    const res = await fetch(`${BASE}/study-materials/upload/`, {
      method: 'POST',
      body: formData,
    });
    if (res.ok) return await res.json();
    const err = await res.json();
    console.error('Upload failed:', err);
    return null;
  } catch (e) {
    console.error('Upload error:', e);
    return null;
  }
}

export async function fetchStudyMaterials(): Promise<StudyMaterial[]> {
  try {
    const res = await fetch(`${BASE}/study-materials/`, { method: 'GET' });
    if (res.ok) return await res.json();
  } catch { /* silent */ }
  return [];
}

export async function fetchStudyMaterialStatus(id: number): Promise<StudyMaterial | null> {
  try {
    const res = await fetch(`${BASE}/study-materials/${id}/status/`, { method: 'GET' });
    if (res.ok) return await res.json();
  } catch { /* silent */ }
  return null;
}

export async function queryStudyMaterial(id: number, question: string): Promise<{ answer: string; sources: unknown[]; retrieved_sources: unknown[]; retrieved_chunk_count: number } | null> {
  try {
    const res = await fetch(`${BASE}/study-materials/${id}/query/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    });
    if (res.ok) return await res.json();
  } catch { /* silent */ }
  return null;
}

export async function queryStudyMaterialFile(fileId: number, question: string): Promise<{ answer: string; sources: unknown[]; retrieved_sources: unknown[]; retrieved_chunk_count: number } | null> {
  try {
    const res = await fetch(`${BASE}/study-materials/files/${fileId}/query/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    });
    if (res.ok) return await res.json();
  } catch { /* silent */ }
  return null;
}

export async function retryStudyMaterial(id: number): Promise<{ status: string; study_material_id: number } | null> {
  try {
    const res = await fetch(`${BASE}/study-materials/${id}/retry/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    if (res.ok) return await res.json();
  } catch { /* silent */ }
  return null;
}

export async function mergeToCourse(smId: number, courseId: number): Promise<{ merged_vectorstore_path: string; study_material: unknown } | null> {
  try {
    const res = await fetch(`${BASE}/study-materials/${smId}/merge-to-course/${courseId}/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    if (res.ok) return await res.json();
  } catch { /* silent */ }
  return null;
}

export async function deleteStudyMaterial(smId: number): Promise<{ success: boolean; error?: string }> {
  try {
    const res = await fetch(`${BASE}/study-materials/${smId}/delete/`, {
      method: 'DELETE',
    });
    const data = await res.json();
    if (res.ok) {
      return { success: true };
    }
    return { success: false, error: data.error || 'Failed to delete' };
  } catch (err) {
    return { success: false, error: String(err) };
  }
}

export async function fetchCourses(): Promise<Course[]> {
  try {
    const res = await fetch(`${BASE}/courses/list/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    if (res.ok) {
      const json = await res.json();
      return json.courses ?? json;
    }
  } catch { /* silent */ }
  return [];
}
