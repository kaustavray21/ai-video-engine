/* ── API service layer V2 ── */

import type { ApiCallLog, DashboardStats } from '../types';

const BASE = '/api';

export async function sendRequest(
  endpoint: string,
  method: string = 'POST',
  body?: string,
  headers?: Record<string, string>,
): Promise<{ data: unknown; status: number; statusText: string; latencyMs: number }> {
  const url = endpoint.startsWith('http') || endpoint.startsWith(BASE) ? endpoint : `${BASE}${endpoint}`;
  const start = performance.now();

  try {
    const opts: RequestInit = {
      method,
      headers: headers ?? { 'Content-Type': 'application/json' },
    };
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
