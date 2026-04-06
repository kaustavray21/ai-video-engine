interface Props {
  totalVideos: number;
  processedVideos: number;
  totalApiCalls: number;
}

export default function KeyInsights({ totalVideos, processedVideos, totalApiCalls }: Props) {
  const fmt = (n: number) => n.toLocaleString();

  return (
    <div className="bg-[#0a0a0a] border border-zinc-900 rounded-lg p-5">
      <h2 className="text-sm font-medium text-zinc-100 mb-6">Key Insights</h2>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <div className="text-xs text-zinc-500 mb-1">Videos processed</div>
          <div className="text-3xl font-bold text-white tracking-tight">
            {fmt(processedVideos)}
            <span className="text-sm text-zinc-500 font-normal ml-1">/ {fmt(totalVideos)}</span>
          </div>
        </div>
        <div>
          <div className="text-xs text-zinc-500 mb-1">API calls made</div>
          <div className="text-3xl font-bold text-white tracking-tight">{fmt(totalApiCalls)}</div>
        </div>
      </div>
    </div>
  );
}
