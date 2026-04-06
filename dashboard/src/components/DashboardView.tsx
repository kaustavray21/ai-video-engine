import { useEffect, useState } from 'react';
import { MoreHorizontal, Plus, Globe } from 'lucide-react';
import { fetchDashboardStats, fetchLogs } from '../services/api';
import type { ApiCallLog, DashboardStats } from '../types';
import ApiCallChart from './ApiCallChart';
import LogsTable from './LogsTable';
import KeyInsights from './KeyInsights';

export default function DashboardView() {
  const [stats, setStats] = useState<DashboardStats>({
    total_api_calls: 0,
    total_videos: 0,
    processed_videos: 0,
    chart_data: [],
  });
  const [logs, setLogs] = useState<ApiCallLog[]>([]);

  useEffect(() => {
    fetchDashboardStats().then(setStats);
    fetchLogs({ limit: 6 }).then((res) => setLogs(res.logs));
  }, []);

  // Refresh every 30 seconds; skip when the browser tab is hidden to
  // prevent Chrome from parsing megabytes of log JSON in the background.
  useEffect(() => {
    const poll = () => {
      if (document.hidden) return;
      fetchDashboardStats().then(setStats);
      fetchLogs({ limit: 6 }).then((res) => setLogs(res.logs));
    };
    const t = setInterval(poll, 30000);
    return () => clearInterval(t);
  }, []);


  return (
    <div className="grid grid-cols-12 gap-6 max-w-[1600px] mx-auto">
      {/* ── Left column (8 cols) ── */}
      <div className="col-span-12 xl:col-span-8 flex flex-col gap-6">
        {/* API Calls Chart */}
        <div className="bg-[#0a0a0a] border border-zinc-900 rounded-lg p-5">
          <div className="flex justify-between items-center mb-6">
            <h2 className="text-sm font-medium text-zinc-100">API Calls</h2>
            <button className="text-zinc-500 hover:text-white">
              <MoreHorizontal className="w-5 h-5" />
            </button>
          </div>
          <ApiCallChart chartData={stats.chart_data} />
        </div>

        {/* Logs Table */}
        <LogsTable logs={logs} />
      </div>

      {/* ── Right column (4 cols) ── */}
      <div className="col-span-12 xl:col-span-4 flex flex-col gap-6">
        {/* Key Insights */}
        <KeyInsights
          totalVideos={stats.total_videos}
          processedVideos={stats.processed_videos}
          totalApiCalls={stats.total_api_calls}
        />

        {/* Data Sources */}
        <div className="bg-[#0a0a0a] border border-zinc-900 rounded-lg p-5">
          <div className="flex justify-between items-center mb-6">
            <h2 className="text-sm font-medium text-zinc-100">Data Sources</h2>
            <button className="text-zinc-500 hover:text-white">
              <MoreHorizontal className="w-5 h-5" />
            </button>
          </div>
          <div className="grid grid-cols-4 gap-3">
            <div className="border border-dashed border-zinc-700 rounded-lg h-24 flex flex-col items-center justify-center text-zinc-500 hover:bg-zinc-900/50 cursor-pointer">
              <Plus className="w-5 h-5 mb-2 text-[#f05a28]" />
              <span className="text-xs">New</span>
            </div>
            <div className="border border-zinc-800 bg-[#0f0f0f] rounded-lg h-24 flex flex-col items-center justify-center hover:border-zinc-600 transition-colors cursor-pointer">
              <Globe className="w-6 h-6 mb-2 text-white" />
              <span className="text-xs text-zinc-300 font-medium">Vimeo</span>
              <span className="text-[10px] text-zinc-600">API Source</span>
            </div>
            <div className="border border-zinc-800 bg-[#0f0f0f] rounded-lg h-24 flex flex-col items-center justify-center hover:border-zinc-600 transition-colors cursor-pointer">
              <div className="text-xl font-bold mb-1 text-white">F</div>
              <span className="text-xs text-zinc-300 font-medium">FAISS</span>
              <span className="text-[10px] text-zinc-600">Vectorstore</span>
            </div>
            <div className="border border-zinc-800 bg-[#0f0f0f] rounded-lg h-24 flex flex-col items-center justify-center hover:border-zinc-600 transition-colors cursor-pointer">
              <div className="text-xl font-bold mb-1 text-white">AI</div>
              <span className="text-xs text-zinc-300 font-medium">OpenAI</span>
              <span className="text-[10px] text-zinc-600">GPT + Whisper</span>
            </div>
          </div>
        </div>

        {/* API Test code snippet */}
        <div className="bg-[#0a0a0a] border border-zinc-900 rounded-lg p-5 flex-1">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-sm font-medium text-zinc-100">API Test</h2>
            <button className="text-zinc-500 hover:text-white">
              <MoreHorizontal className="w-5 h-5" />
            </button>
          </div>
          <div className="flex gap-4 border-b border-zinc-900 pb-2 mb-4 text-xs">
            <button className="text-white font-medium border-b-2 border-white pb-2 -mb-2">Python</button>
            <button className="text-zinc-500 hover:text-zinc-300">JavaScript</button>
            <button className="text-zinc-500 hover:text-zinc-300">cURL</button>
          </div>
          <div className="font-mono text-xs leading-relaxed">
            <span className="text-blue-400">import</span> <span className="text-yellow-200">requests</span><br /><br />
            <span className="text-zinc-400">resp</span> = requests.<span className="text-yellow-200">post</span>(<br />
            &nbsp;&nbsp;<span className="text-green-400">"/api/courses/list/"</span>,<br />
            &nbsp;&nbsp;<span className="text-pink-400">headers</span>={'{'}<span className="text-green-400">"Content-Type"</span>: <span className="text-green-400">"application/json"</span>{'}'}<br />
            )<br />
            <span className="text-blue-400">print</span>(resp.<span className="text-yellow-200">json</span>())
          </div>
        </div>
      </div>
    </div>
  );
}
