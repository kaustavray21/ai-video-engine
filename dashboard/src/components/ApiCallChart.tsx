interface Props {
  chartData: { date: string; count: number }[];
}

export default function ApiCallChart({ chartData }: Props) {
  const maxCount = Math.max(...chartData.map(d => d.count), 1);
  // Round up to a nice number for Y axis
  const yMax = Math.ceil(maxCount / 10) * 10 || 10;
  const ySteps = 5;

  // Build SVG path from data
  const buildPath = (): string => {
    if (chartData.length === 0) return '';
    const points = chartData.map((d, i) => {
      const x = chartData.length === 1 ? 50 : (i / (chartData.length - 1)) * 100;
      const y = 100 - (d.count / yMax) * 100;
      return `${x} ${y}`;
    });
    return `M ${points.join(' L ')}`;
  };

  const getDayLabel = (dateStr: string): string => {
    const d = new Date(dateStr + 'T00:00:00');
    return d.toLocaleDateString('en-US', { weekday: 'short' });
  };

  return (
    <div className="relative h-64 w-full mt-4 flex">
      {/* Y-axis labels */}
      <div className="flex flex-col justify-between text-xs text-zinc-600 pr-4 pb-6 border-r border-zinc-900">
        {Array.from({ length: ySteps + 1 }, (_, i) => (
          <span key={i}>{Math.round(yMax - (yMax / ySteps) * i)}</span>
        ))}
      </div>

      <div className="flex-1 relative ml-4">
        {/* Grid lines */}
        <div className="absolute inset-0 flex justify-between">
          {Array.from({ length: Math.min(chartData.length, 8) }, (_, i) => (
            <div key={i} className="h-full w-px border-l border-dashed border-zinc-800/50" />
          ))}
        </div>

        {/* Forecast zone (last segment) */}
        {chartData.length > 1 && (
          <div className="absolute right-0 top-0 bottom-6 bg-zinc-800/20 border-l border-dashed border-zinc-700"
               style={{ width: `${100 / Math.max(chartData.length - 1, 1)}%` }}>
            <div className="w-full h-full"
                 style={{ backgroundImage: 'repeating-linear-gradient(45deg, transparent, transparent 2px, rgba(255,255,255,0.05) 2px, rgba(255,255,255,0.05) 4px)' }} />
          </div>
        )}

        {/* Chart line */}
        {chartData.length > 0 && (
          <svg className="absolute inset-0 h-[calc(100%-1.5rem)] w-full" preserveAspectRatio="none" viewBox="0 0 100 100">
            <path
              d={buildPath()}
              fill="none"
              stroke="white"
              strokeWidth="2"
              vectorEffect="non-scaling-stroke"
            />
          </svg>
        )}

        {chartData.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center text-zinc-600 text-xs">
            No data yet
          </div>
        )}

        {/* X-axis labels */}
        <div className="absolute bottom-0 left-0 right-0 flex justify-between text-xs text-zinc-600">
          {chartData.slice(-9).map((d, i) => (
            <span key={i}>{getDayLabel(d.date)}</span>
          ))}
        </div>
      </div>
    </div>
  );
}
