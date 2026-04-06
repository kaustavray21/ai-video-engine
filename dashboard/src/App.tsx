import { useState } from 'react';
import Sidebar from './components/Sidebar';
import Header from './components/Header';
import DashboardView from './components/DashboardView';
import ApiTesterView from './components/ApiTesterView';
import HistoryView from './components/HistoryView';
import './index.css';

type Tab = 'dashboard' | 'api' | 'history';

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>('dashboard');

  return (
    <div className="flex h-screen bg-[#000000] text-zinc-100 font-sans overflow-hidden">
      <Sidebar activeTab={activeTab} onTabChange={setActiveTab} />

      <div className="flex-1 flex flex-col h-full overflow-hidden bg-[#050505]">
        <Header activeTab={activeTab} />

        {/*
          All three views are always mounted — only visibility changes.
          This preserves ApiTesterView's complete state (URL, headers,
          request body, response) when the user switches to another tab.
        */}
        <div className="flex-1 overflow-y-auto p-6">
          <div style={{ display: activeTab === 'dashboard' ? 'block' : 'none' }}>
            <DashboardView />
          </div>
          <div style={{ display: activeTab === 'api' ? 'block' : 'none' }}>
            <ApiTesterView />
          </div>
          <div style={{ display: activeTab === 'history' ? 'block' : 'none' }}>
            <HistoryView />
          </div>
        </div>
      </div>
    </div>
  );
}
