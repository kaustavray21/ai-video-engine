import { LayoutGrid, Activity, Clock, Hexagon, FileArchive } from 'lucide-react';

type Tab = 'dashboard' | 'api' | 'history' | 'materials';

interface Props {
  activeTab: Tab;
  onTabChange: (tab: Tab) => void;
}

const navItems: { key: Tab; icon: typeof LayoutGrid; label: string }[] = [
  { key: 'dashboard', icon: LayoutGrid,  label: 'Dashboard' },
  { key: 'api',       icon: Activity,    label: 'API Tester' },
  { key: 'history',   icon: Clock,       label: 'History' },
  { key: 'materials', icon: FileArchive, label: 'Study Materials' },
];

export default function Sidebar({ activeTab, onTabChange }: Props) {
  return (
    <div className="w-16 flex flex-col items-center py-4 border-r border-zinc-900 bg-[#050505] shrink-0">
      <div className="mb-8">
        <Hexagon className="w-8 h-8 text-white fill-white" />
      </div>

      <nav className="flex-1 flex flex-col gap-4 w-full px-2">
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.key}
              onClick={() => onTabChange(item.key)}
              title={item.label}
              className={`w-full flex justify-center py-3 rounded-xl transition-colors ${
                activeTab === item.key
                  ? 'bg-[#f05a28] text-white'
                  : 'text-zinc-500 hover:text-white hover:bg-zinc-900'
              }`}
            >
              <Icon className="w-5 h-5" />
            </button>
          );
        })}
      </nav>
    </div>
  );
}
