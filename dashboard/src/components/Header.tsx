import { Plus } from 'lucide-react';

interface Props {
  activeTab: string;
}

const titles: Record<string, string> = {
  dashboard: 'Dashboard',
  api: 'API Tester',
  history: 'History',
  materials: 'Study Materials',
};

export default function Header({ activeTab }: Props) {
  return (
    <header className="h-16 flex items-center justify-between px-8 border-b border-zinc-900 shrink-0">
      <h1 className="text-xl font-medium tracking-wide">
        {titles[activeTab] ?? 'Dashboard'}
      </h1>
      <button className="bg-[#f05a28] hover:bg-[#d4481c] text-white px-4 py-2 rounded-md font-medium transition-colors flex items-center gap-2 text-sm">
        <Plus className="w-4 h-4" />
        AI Assistant
      </button>
    </header>
  );
}
