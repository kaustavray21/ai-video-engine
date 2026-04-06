import { MoreHorizontal } from 'lucide-react';
import type { ApiCallLog } from '../types';

interface Props {
  logs: ApiCallLog[];
}

export default function LogsTable({ logs }: Props) {
  return (
    <div className="bg-[#0a0a0a] border border-zinc-900 rounded-lg p-5">
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-sm font-medium text-zinc-100">Logs</h2>
        <button className="text-zinc-500 hover:text-white">
          <MoreHorizontal className="w-5 h-5" />
        </button>
      </div>

      <div className="w-full text-left text-sm">
        <div className="grid grid-cols-12 text-zinc-600 pb-3 border-b border-zinc-900 text-xs">
          <div className="col-span-6">Request</div>
          <div className="col-span-3">Status</div>
          <div className="col-span-3">Time</div>
        </div>
        {logs.length === 0 ? (
          <div className="py-8 text-center text-zinc-600 text-xs">No logs recorded yet.</div>
        ) : (
          logs.slice(0, 6).map((log, i) => (
            <div
              key={log.id}
              className={`grid grid-cols-12 py-4 text-zinc-300 ${
                i !== Math.min(logs.length, 6) - 1 ? 'border-b border-zinc-900/50' : ''
              }`}
            >
              <div className="col-span-6 font-medium text-zinc-100 truncate pr-4">
                <span className="text-zinc-500 mr-2 text-[10px]">{log.method}</span>
                {log.endpoint}
              </div>
              <div className="col-span-3">
                <span
                  className={
                    log.status_code >= 200 && log.status_code < 300
                      ? 'text-emerald-400'
                      : 'text-red-400'
                  }
                >
                  {log.status_code || 'Err'} {log.status_text}
                </span>
              </div>
              <div className="col-span-3 text-zinc-500 text-xs truncate">
                {new Date(log.created_at).toLocaleString()}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
