import { useState, useEffect } from 'react';
import { Clock, Search, Database } from 'lucide-react';
import { fetchLogs } from '../services/api';
import type { ApiCallLog } from '../types';

export default function HistoryView() {
  const [filterDate, setFilterDate] = useState('');
  const [logs, setLogs] = useState<ApiCallLog[]>([]);
  const [loading, setLoading] = useState(false);

  const loadHistory = async () => {
    setLoading(true);
    const params: { saved_only: boolean; date?: string; limit: number } = {
      saved_only: true,
      limit: 100,
    };
    if (filterDate) params.date = filterDate;
    const res = await fetchLogs(params);
    setLogs(res.logs);
    setLoading(false);
  };

  useEffect(() => {
    loadHistory();
  }, [filterDate]);

  const methodColor = (m: string) => {
    if (m === 'GET') return 'bg-blue-900/30 text-blue-400';
    if (m === 'POST') return 'bg-emerald-900/30 text-emerald-400';
    if (m === 'DELETE') return 'bg-red-900/30 text-red-400';
    return 'bg-orange-900/30 text-orange-400';
  };

  return (
    <div className="max-w-[1200px] mx-auto">
      {/* Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-6 gap-4 border-b border-zinc-900 pb-4">
        <h1 className="text-xl font-medium text-zinc-100 flex items-center gap-2">
          <Clock className="w-5 h-5 text-[#f05a28]" />
          Request History
        </h1>

        <div className="relative w-full md:w-64">
          <Search className="w-4 h-4 absolute left-3 top-1/2 transform -translate-y-1/2 text-zinc-500" />
          <input
            type="date"
            value={filterDate}
            onChange={(e) => setFilterDate(e.target.value)}
            className="w-full bg-[#0a0a0a] border border-zinc-800 rounded-lg pl-9 pr-4 py-2 outline-none focus:border-[#f05a28] text-sm text-zinc-100"
            style={{ colorScheme: 'dark' }}
          />
        </div>
      </div>

      {loading && (
        <div className="text-center py-12 text-zinc-500 text-sm">Loading...</div>
      )}

      {!loading && logs.length === 0 && (
        <div className="flex flex-col items-center justify-center h-64 text-zinc-600">
          <Database className="w-12 h-12 mb-4 opacity-20" />
          <p className="text-sm">No saved requests found.</p>
          <p className="text-xs text-zinc-700 mt-1">
            Use "Save to DB" in the API Tester to save requests here.
          </p>
        </div>
      )}

      {!loading && logs.length > 0 && (
        <div className="space-y-6">
          {logs.map((item) => (
            <div key={item.id} className="bg-[#0a0a0a] rounded-xl border border-zinc-900 overflow-hidden">
              {/* Header bar */}
              <div className="bg-[#0f0f0f] border-b border-zinc-900 px-6 py-3 flex justify-between items-center flex-wrap gap-2">
                <div className="flex items-center gap-3">
                  <span className={`px-2 py-1 rounded text-[10px] font-bold ${methodColor(item.method)}`}>
                    {item.method}
                  </span>
                  <span className="font-mono text-sm text-zinc-300 break-all">{item.endpoint}</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-zinc-600">{item.latency_ms}ms</span>
                  <div className="text-xs text-zinc-500">
                    {new Date(item.created_at).toLocaleString()}
                  </div>
                </div>
              </div>

              {/* Request / Response */}
              <div className="p-6 grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div>
                  <h3 className="text-xs font-medium text-zinc-500 mb-2 uppercase tracking-wider">Request</h3>
                  <div className="bg-[#0f0f0f] p-4 rounded-lg border border-zinc-800 min-h-[100px] font-mono text-xs overflow-auto whitespace-pre-wrap text-zinc-400">
                    {item.request_body || 'No body content'}
                  </div>
                </div>

                <div>
                  <div className="flex justify-between items-center mb-2">
                    <h3 className="text-xs font-medium text-zinc-500 uppercase tracking-wider">Response</h3>
                    <span
                      className={`text-[10px] font-bold px-2 py-0.5 rounded ${
                        item.status_code >= 200 && item.status_code < 300
                          ? 'bg-emerald-900/30 text-emerald-400'
                          : 'bg-red-900/30 text-red-400'
                      }`}
                    >
                      {item.status_code} {item.status_text}
                    </span>
                  </div>
                  <div className="bg-[#0f0f0f] text-emerald-400 p-4 rounded-lg border border-zinc-800 min-h-[100px] max-h-[300px] font-mono text-xs overflow-auto whitespace-pre-wrap">
                    {item.response_body || 'No response data'}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
