import React, { useState } from 'react';
import { Play, Clock, Search, Database, LayoutGrid, Globe, Plus, X, Hexagon, MoreHorizontal, Activity, FileJson } from 'lucide-react';

interface HeaderItem {
    key: string;
    value: string;
}

interface HistoryEntry {
    id: number;
    date: string;
    isoDate: string;
    method: string;
    url: string;
    requestBody: string;
    responseBody: string;
    status: string;
    statusCode: number | string;
}

export default function App() {
    const commonHeaders: string[] = [
        'Accept', 'Accept-Charset', 'Accept-Encoding', 'Accept-Language',
        'Authorization', 'Cache-Control', 'Connection', 'Content-Length',
        'Content-Type', 'Cookie', 'Date', 'Expect', 'Forwarded', 'From',
        'Host', 'If-Match', 'If-Modified-Since', 'If-None-Match',
        'If-Range', 'If-Unmodified-Since', 'Max-Forwards', 'Origin',
        'Pragma', 'Proxy-Authorization', 'Range', 'Referer', 'TE',
        'User-Agent', 'Upgrade', 'Via', 'Warning', 'X-Requested-With',
        'X-Forwarded-For', 'X-Forwarded-Host', 'X-Forwarded-Proto',
        'X-API-Key', 'X-Auth-Token'
    ];

    const [activeTab, setActiveTab] = useState<string>('dashboard');

    const [method, setMethod] = useState<string>('GET');
    const [url, setUrl] = useState<string>('https://jsonplaceholder.typicode.com/posts/1');
    const [requestBody, setRequestBody] = useState<string>('');

    const [headersList, setHeadersList] = useState<HeaderItem[]>([{ key: 'Content-Type', value: 'application/json' }]);

    const [responseBody, setResponseBody] = useState<string>('');
    const [status, setStatus] = useState<string>('');
    const [statusCode, setStatusCode] = useState<number | string>('');
    const [isLoadings, setIsLoading] = useState<boolean>(false);

    const [history, setHistory] = useState<HistoryEntry[]>([]);
    const [filterDate, setFilterDate] = useState<string>('');

    const handleSend = async (): Promise<void> => {
        setIsLoading(true);
        setResponseBody('');
        setStatus('');
        setStatusCode('');

        try {
            const activeHeaders: Record<string, string> = {};
            headersList.forEach(h => {
                if (h.key.trim()) {
                    activeHeaders[h.key.trim()] = h.value;
                }
            });

            const options: RequestInit = {
                method,
                headers: activeHeaders,
            };

            if (method !== 'GET' && method !== 'HEAD' && requestBody) {
                options.body = requestBody;
            }

            const res = await fetch(url, options);

            setStatusCode(res.status);
            setStatus(res.statusText || (res.ok ? 'OK' : 'Error'));

            const contentType = res.headers.get('content-type');
            if (contentType && contentType.indexOf('application/json') !== -1) {
                const data = await res.json();
                setResponseBody(JSON.stringify(data, null, 2));
            } else {
                const text = await res.text();
                setResponseBody(text);
            }
        } catch (error: any) {
            setStatusCode('ERR');
            setStatus('Failed to fetch');
            setResponseBody(error.toString());
        } finally {
            setIsLoading(false);
        }
    };

    const handleSave = (): void => {
        if (!url) return;

        const now = new Date();
        const offset = now.getTimezoneOffset();
        const localDate = new Date(now.getTime() - (offset * 60 * 1000));

        const newEntry: HistoryEntry = {
            id: Date.now(),
            date: now.toLocaleString(),
            isoDate: localDate.toISOString().split('T')[0],
            method,
            url,
            requestBody,
            responseBody,
            status,
            statusCode
        };

        setHistory([newEntry, ...history]);
    };

    const filteredHistory: HistoryEntry[] = filterDate
        ? history.filter(item => item.isoDate === filterDate)
        : history;

    return (
        <div className="flex h-screen bg-[#000000] text-zinc-100 font-sans overflow-hidden">
            <div className="w-16 flex flex-col items-center py-4 border-r border-zinc-900 bg-[#050505] shrink-0">
                <div className="mb-8">
                    <Hexagon className="w-8 h-8 text-white fill-white" />
                </div>

                <nav className="flex-1 flex flex-col gap-4 w-full px-2">
                    <button
                        onClick={() => setActiveTab('dashboard')}
                        className={`w-full flex justify-center py-3 rounded-xl transition-colors ${activeTab === 'dashboard'
                                ? 'bg-[#f05a28] text-white'
                                : 'text-zinc-500 hover:text-white hover:bg-zinc-900'
                            }`}
                    >
                        <LayoutGrid className="w-5 h-5" />
                    </button>

                    <button
                        onClick={() => setActiveTab('api')}
                        className={`w-full flex justify-center py-3 rounded-xl transition-colors ${activeTab === 'api'
                                ? 'bg-[#f05a28] text-white'
                                : 'text-zinc-500 hover:text-white hover:bg-zinc-900'
                            }`}
                    >
                        <Activity className="w-5 h-5" />
                    </button>

                    <button
                        onClick={() => setActiveTab('history')}
                        className={`w-full flex justify-center py-3 rounded-xl transition-colors ${activeTab === 'history'
                                ? 'bg-[#f05a28] text-white'
                                : 'text-zinc-500 hover:text-white hover:bg-zinc-900'
                            }`}
                    >
                        <Clock className="w-5 h-5" />
                    </button>
                </nav>
            </div>

            <div className="flex-1 flex flex-col h-full overflow-hidden bg-[#050505]">
                <header className="h-16 flex items-center justify-between px-8 border-b border-zinc-900 shrink-0">
                    <h1 className="text-xl font-medium tracking-wide">
                        {activeTab === 'dashboard' ? 'Dashboard' : activeTab === 'api' ? 'API Tester' : 'History'}
                    </h1>
                    <button className="bg-[#f05a28] hover:bg-[#d4481c] text-white px-4 py-2 rounded-md font-medium transition-colors flex items-center gap-2 text-sm">
                        <Plus className="w-4 h-4" />
                        AI Assistant
                    </button>
                </header>

                <div className="flex-1 overflow-y-auto p-6">
                    {activeTab === 'dashboard' && (
                        <div className="grid grid-cols-12 gap-6 max-w-[1600px] mx-auto">
                            <div className="col-span-12 xl:col-span-8 flex flex-col gap-6">
                                <div className="bg-[#0a0a0a] border border-zinc-900 rounded-lg p-5">
                                    <div className="flex justify-between items-center mb-6">
                                        <h2 className="text-sm font-medium text-zinc-100">API Calls</h2>
                                        <button className="text-zinc-500 hover:text-white"><MoreHorizontal className="w-5 h-5" /></button>
                                    </div>

                                    <div className="relative h-64 w-full mt-4 flex">
                                        <div className="flex flex-col justify-between text-xs text-zinc-600 pr-4 pb-6 border-r border-zinc-900">
                                            <span>500</span>
                                            <span>400</span>
                                            <span>300</span>
                                            <span>200</span>
                                            <span>100</span>
                                            <span>0</span>
                                        </div>

                                        <div className="flex-1 relative ml-4">
                                            <div className="absolute inset-0 flex justify-between">
                                                {[...Array(8)].map((_, i) => (
                                                    <div key={i} className="h-full w-px border-l border-dashed border-zinc-800/50"></div>
                                                ))}
                                            </div>

                                            <div className="absolute right-0 top-0 bottom-6 w-[12.5%] bg-zinc-800/20 border-l border-dashed border-zinc-700">
                                                <div className="w-full h-full" style={{ backgroundImage: 'repeating-linear-gradient(45deg, transparent, transparent 2px, rgba(255,255,255,0.05) 2px, rgba(255,255,255,0.05) 4px)' }}></div>
                                            </div>

                                            <svg className="absolute inset-0 h-[calc(100%-1.5rem)] w-full" preserveAspectRatio="none" viewBox="0 0 100 100">
                                                <path
                                                    d="M 0 100 L 14.2 45 L 28.5 70 L 42.8 40 L 57.1 30 L 71.4 15 L 85.7 60 L 100 40"
                                                    fill="none"
                                                    stroke="white"
                                                    strokeWidth="2"
                                                    vectorEffect="non-scaling-stroke"
                                                />
                                                <path
                                                    d="M 85.7 60 L 100 40"
                                                    fill="none"
                                                    stroke="#a1a1aa"
                                                    strokeWidth="2"
                                                    strokeDasharray="4 4"
                                                    vectorEffect="non-scaling-stroke"
                                                />
                                            </svg>

                                            <div className="absolute bottom-0 left-0 right-0 flex justify-between text-xs text-zinc-600 -ml-2">
                                                <span>Sun</span>
                                                <span>Mon</span>
                                                <span>Tue</span>
                                                <span>Wed</span>
                                                <span>Thu</span>
                                                <span>Fri</span>
                                                <span>Sat</span>
                                                <span>Sun</span>
                                                <span>Mon</span>
                                            </div>
                                        </div>
                                    </div>
                                </div>

                                <div className="bg-[#0a0a0a] border border-zinc-900 rounded-lg p-5">
                                    <div className="flex justify-between items-center mb-6">
                                        <h2 className="text-sm font-medium text-zinc-100">Logs</h2>
                                        <button className="text-zinc-500 hover:text-white"><MoreHorizontal className="w-5 h-5" /></button>
                                    </div>

                                    <div className="w-full text-left text-sm">
                                        <div className="grid grid-cols-12 text-zinc-600 pb-3 border-b border-zinc-900 text-xs">
                                            <div className="col-span-6">Request</div>
                                            <div className="col-span-3">Status</div>
                                            <div className="col-span-3">Time</div>
                                        </div>
                                        {history.length === 0 ? (
                                            <div className="py-8 text-center text-zinc-600 text-xs">No logs recorded in this session.</div>
                                        ) : (
                                            history.slice(0, 4).map((log, i) => (
                                                <div key={log.id} className={`grid grid-cols-12 py-4 text-zinc-300 ${i !== Math.min(history.length, 4) - 1 ? 'border-b border-zinc-900/50' : ''}`}>
                                                    <div className="col-span-6 font-medium text-zinc-100 truncate pr-4">
                                                        <span className="text-zinc-500 mr-2 text-[10px]">{log.method}</span>
                                                        {log.url}
                                                    </div>
                                                    <div className="col-span-3">
                                                        <span className={log.statusCode >= 200 && log.statusCode < 300 ? 'text-emerald-400' : 'text-red-400'}>
                                                            {log.statusCode || 'Err'} {log.status}
                                                        </span>
                                                    </div>
                                                    <div className="col-span-3 text-zinc-500 text-xs truncate">{log.date}</div>
                                                </div>
                                            ))
                                        )}
                                    </div>
                                </div>
                            </div>

                            <div className="col-span-12 xl:col-span-4 flex flex-col gap-6">
                                <div className="bg-[#0a0a0a] border border-zinc-900 rounded-lg p-5">
                                    <h2 className="text-sm font-medium text-zinc-100 mb-6">Key Insights</h2>
                                    <div className="grid grid-cols-2 gap-4">
                                        <div>
                                            <div className="text-xs text-zinc-500 mb-1">Videos processed</div>
                                            <div className="text-3xl font-bold text-white tracking-tight">435,016</div>
                                        </div>
                                        <div>
                                            <div className="text-xs text-zinc-500 mb-1">API calls made</div>
                                            <div className="text-3xl font-bold text-white tracking-tight">25,879</div>
                                        </div>
                                    </div>
                                </div>

                                <div className="bg-[#0a0a0a] border border-zinc-900 rounded-lg p-5">
                                    <div className="flex justify-between items-center mb-6">
                                        <h2 className="text-sm font-medium text-zinc-100">Data Sources</h2>
                                        <button className="text-zinc-500 hover:text-white"><MoreHorizontal className="w-5 h-5" /></button>
                                    </div>
                                    <div className="grid grid-cols-4 gap-3">
                                        <div className="border border-dashed border-zinc-700 rounded-lg h-24 flex flex-col items-center justify-center text-zinc-500 hover:bg-zinc-900/50 cursor-pointer">
                                            <Plus className="w-5 h-5 mb-2 text-[#f05a28]" />
                                            <span className="text-xs">New</span>
                                        </div>
                                        <div className="border border-zinc-800 bg-[#0f0f0f] rounded-lg h-24 flex flex-col items-center justify-center hover:border-zinc-600 transition-colors cursor-pointer">
                                            <Globe className="w-6 h-6 mb-2 text-white" />
                                            <span className="text-xs text-zinc-300 font-medium">Weibo</span>
                                            <span className="text-[10px] text-zinc-600">Avg 4h docs</span>
                                        </div>
                                        <div className="border border-zinc-800 bg-[#0f0f0f] rounded-lg h-24 flex flex-col items-center justify-center hover:border-zinc-600 transition-colors cursor-pointer">
                                            <div className="text-xl font-bold mb-1 text-white">D</div>
                                            <span className="text-xs text-zinc-300 font-medium">Dow Jones</span>
                                            <span className="text-[10px] text-zinc-600">Avg 73k docs</span>
                                        </div>
                                        <div className="border border-zinc-800 bg-[#0f0f0f] rounded-lg h-24 flex flex-col items-center justify-center hover:border-zinc-600 transition-colors cursor-pointer">
                                            <div className="text-xl font-bold mb-1 text-white">VK</div>
                                            <span className="text-xs text-zinc-300 font-medium">VKontakte</span>
                                            <span className="text-[10px] text-zinc-600">Avg 6h docs</span>
                                        </div>
                                    </div>
                                </div>

                                <div className="bg-[#0a0a0a] border border-zinc-900 rounded-lg p-5 flex-1">
                                    <div className="flex justify-between items-center mb-4">
                                        <h2 className="text-sm font-medium text-zinc-100">API Test</h2>
                                        <button className="text-zinc-500 hover:text-white"><MoreHorizontal className="w-5 h-5" /></button>
                                    </div>
                                    <div className="flex gap-4 border-b border-zinc-900 pb-2 mb-4 text-xs">
                                        <button className="text-white font-medium border-b-2 border-white pb-2 -mb-2">Python</button>
                                        <button className="text-zinc-500 hover:text-zinc-300">JavaScript</button>
                                        <button className="text-zinc-500 hover:text-zinc-300">Go</button>
                                        <button className="text-zinc-500 hover:text-zinc-300">Java</button>
                                    </div>
                                    <div className="font-mono text-xs leading-relaxed">
                                        <span className="text-blue-400">const</span> axios = <span className="text-yellow-200">require</span>(<span className="text-green-400">'axios'</span>);<br /><br />
                                        <span className="text-blue-400">const</span> options = {'{'}<br />
                                        &nbsp;&nbsp;<span className="text-pink-400">method:</span> <span className="text-green-400">'GET'</span>,<br />
                                        &nbsp;&nbsp;<span className="text-pink-400">url:</span> <span className="text-green-400">'https://api...</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}

                    {activeTab === 'api' && (
                        <div className="max-w-[1200px] mx-auto flex flex-col gap-6">
                            <div className="bg-[#0a0a0a] rounded-xl border border-zinc-900 p-6">
                                <div className="flex flex-col md:flex-row gap-4 mb-6">
                                    <div className="flex bg-[#0f0f0f] rounded-lg p-1 border border-zinc-800 w-full md:w-auto">
                                        <select
                                            value={method}
                                            onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setMethod(e.target.value)}
                                            className="bg-transparent font-medium text-zinc-300 px-4 py-2 outline-none cursor-pointer border-r border-zinc-800 focus:ring-1 focus:ring-[#f05a28] rounded-l-md"
                                        >
                                            <option value="GET">GET</option>
                                            <option value="POST">POST</option>
                                            <option value="PUT">PUT</option>
                                            <option value="PATCH">PATCH</option>
                                            <option value="DELETE">DELETE</option>
                                        </select>

                                        <div className="flex-1 flex items-center px-3 bg-[#0f0f0f] w-full min-w-[300px] rounded-r-md">
                                            <Globe className="w-4 h-4 text-zinc-500 mr-2" />
                                            <input
                                                type="text"
                                                value={url}
                                                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setUrl(e.target.value)}
                                                placeholder="Select or enter URL"
                                                className="w-full bg-transparent py-2 outline-none text-zinc-100 placeholder:text-zinc-600"
                                            />
                                        </div>
                                    </div>

                                    <button
                                        onClick={handleSend}
                                        disabled={isLoadings}
                                        className="bg-[#f05a28] hover:bg-[#d4481c] text-white px-6 py-2 rounded-lg font-medium transition-colors flex items-center gap-2 justify-center shadow-sm disabled:opacity-70 disabled:cursor-not-allowed"
                                    >
                                        <Play className="w-4 h-4" />
                                        {isLoadings ? 'Sending...' : 'Send'}
                                    </button>
                                </div>

                                <div className="mb-6">
                                    <div className="flex justify-between items-center mb-3">
                                        <label className="block text-sm font-medium text-zinc-300">
                                            Headers
                                        </label>
                                        <button
                                            onClick={() => setHeadersList([...headersList, { key: '', value: '' }])}
                                            className="text-sm text-[#f05a28] hover:text-[#d4481c] flex items-center gap-1 font-medium"
                                        >
                                            <Plus className="w-4 h-4" />
                                            Add Header
                                        </button>
                                    </div>

                                    <div className="space-y-2">
                                        <datalist id="common-headers">
                                            {commonHeaders.map(h => <option key={h} value={h} />)}
                                        </datalist>
                                        {headersList.map((header, index) => (
                                            <div key={index} className="flex gap-2 items-center">
                                                <input
                                                    type="text"
                                                    list="common-headers"
                                                    value={header.key}
                                                    onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                                                        const newHeaders = [...headersList];
                                                        newHeaders[index].key = e.target.value;
                                                        setHeadersList(newHeaders);
                                                    }}
                                                    placeholder="Key"
                                                    className="flex-1 bg-[#0f0f0f] border border-zinc-800 rounded-md px-3 py-2 text-sm text-zinc-100 outline-none focus:border-[#f05a28]"
                                                />
                                                <input
                                                    type="text"
                                                    value={header.value}
                                                    onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                                                        const newHeaders = [...headersList];
                                                        newHeaders[index].value = e.target.value;
                                                        setHeadersList(newHeaders);
                                                    }}
                                                    placeholder="Value"
                                                    className="flex-1 bg-[#0f0f0f] border border-zinc-800 rounded-md px-3 py-2 text-sm text-zinc-100 outline-none focus:border-[#f05a28]"
                                                />
                                                <button
                                                    onClick={() => setHeadersList(headersList.filter((_, i) => i !== index))}
                                                    className="p-2 text-zinc-500 hover:text-red-400 hover:bg-zinc-900 rounded-md transition-colors"
                                                >
                                                    <X className="w-4 h-4" />
                                                </button>
                                            </div>
                                        ))}
                                        {headersList.length === 0 && (
                                            <div className="text-sm text-zinc-600 italic py-2">
                                                No headers configured.
                                            </div>
                                        )}
                                    </div>
                                </div>

                                <div>
                                    <label className="block text-sm font-medium text-zinc-300 mb-2">
                                        Body (JSON)
                                    </label>
                                    <textarea
                                        value={requestBody}
                                        onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setRequestBody(e.target.value)}
                                        placeholder={"{\n  \"key\": \"value\"\n}"}
                                        className="w-full h-40 bg-[#0f0f0f] text-zinc-300 p-4 rounded-lg border border-zinc-800 font-mono text-sm outline-none focus:border-[#f05a28] resize-y placeholder:text-zinc-700"
                                        disabled={method === 'GET' || method === 'DELETE'}
                                    />
                                </div>
                            </div>

                            <div className="bg-[#0a0a0a] rounded-xl border border-zinc-900 p-6 flex-1 flex flex-col min-h-[300px]">
                                <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-4 gap-4 border-b border-zinc-900 pb-4">
                                    <h2 className="text-sm font-medium text-zinc-100">Response Body</h2>

                                    <div className="flex flex-wrap items-center gap-3">
                                        {statusCode && (
                                            <div className="flex items-center gap-2 bg-[#0f0f0f] px-3 py-1.5 rounded-lg border border-zinc-800">
                                                <span className="text-xs text-zinc-500 font-medium">Status:</span>
                                                <span className={`text-xs font-bold ${typeof statusCode === 'number' && statusCode >= 200 && statusCode < 300 ? 'text-emerald-400' : 'text-red-400'
                                                    }`}>
                                                    {statusCode} {status}
                                                </span>
                                            </div>
                                        )}

                                        <button
                                            onClick={handleSave}
                                            disabled={!responseBody}
                                            className="bg-[#f05a28] hover:bg-[#d4481c] text-white px-4 py-1.5 rounded-lg font-medium transition-colors flex items-center gap-2 shadow-sm disabled:opacity-50 disabled:cursor-not-allowed text-xs"
                                        >
                                            <Database className="w-4 h-4" />
                                            Save to DB
                                        </button>
                                    </div>
                                </div>

                                <textarea
                                    readOnly
                                    value={responseBody}
                                    placeholder="Response will appear here..."
                                    className="w-full flex-1 bg-[#0f0f0f] text-emerald-400 p-4 rounded-lg border border-zinc-800 font-mono text-sm outline-none resize-none min-h-[250px] placeholder:text-zinc-700"
                                />
                            </div>
                        </div>
                    )}

                    {activeTab === 'history' && (
                        <div className="max-w-[1200px] mx-auto">
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
                                        onChange={(e: React.ChangeEvent<HTMLInputElement>) => setFilterDate(e.target.value)}
                                        className="w-full bg-[#0a0a0a] border border-zinc-800 rounded-lg pl-9 pr-4 py-2 outline-none focus:border-[#f05a28] text-sm text-zinc-100"
                                        style={{ colorScheme: 'dark' }}
                                    />
                                </div>
                            </div>

                            {filteredHistory.length === 0 ? (
                                <div className="flex flex-col items-center justify-center h-64 text-zinc-600">
                                    <Database className="w-12 h-12 mb-4 opacity-20" />
                                    <p className="text-sm">No history found.</p>
                                </div>
                            ) : (
                                <div className="space-y-6">
                                    {filteredHistory.map((item) => (
                                        <div key={item.id} className="bg-[#0a0a0a] rounded-xl border border-zinc-900 overflow-hidden">
                                            <div className="bg-[#0f0f0f] border-b border-zinc-900 px-6 py-3 flex justify-between items-center flex-wrap gap-2">
                                                <div className="flex items-center gap-3">
                                                    <span className={`px-2 py-1 rounded text-[10px] font-bold ${item.method === 'GET' ? 'bg-blue-900/30 text-blue-400' :
                                                            item.method === 'POST' ? 'bg-emerald-900/30 text-emerald-400' :
                                                                item.method === 'DELETE' ? 'bg-red-900/30 text-red-400' :
                                                                    'bg-orange-900/30 text-orange-400'
                                                        }`}>
                                                        {item.method}
                                                    </span>
                                                    <span className="font-mono text-sm text-zinc-300 break-all">{item.url}</span>
                                                </div>
                                                <div className="text-xs text-zinc-500">{item.date}</div>
                                            </div>

                                            <div className="p-6 grid grid-cols-1 lg:grid-cols-2 gap-6">
                                                <div>
                                                    <h3 className="text-xs font-medium text-zinc-500 mb-2 uppercase tracking-wider">Request</h3>
                                                    <div className="bg-[#0f0f0f] p-4 rounded-lg border border-zinc-800 min-h-[100px] font-mono text-xs overflow-auto whitespace-pre-wrap text-zinc-400">
                                                        {item.requestBody || 'No body content'}
                                                    </div>
                                                </div>

                                                <div>
                                                    <div className="flex justify-between items-center mb-2">
                                                        <h3 className="text-xs font-medium text-zinc-500 uppercase tracking-wider">Response</h3>
                                                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded ${typeof item.statusCode === 'number' && item.statusCode >= 200 && item.statusCode < 300 ? 'bg-emerald-900/30 text-emerald-400' : 'bg-red-900/30 text-red-400'
                                                            }`}>
                                                            {item.statusCode} {item.status}
                                                        </span>
                                                    </div>
                                                    <div className="bg-[#0f0f0f] text-emerald-400 p-4 rounded-lg border border-zinc-800 min-h-[100px] max-h-[300px] font-mono text-xs overflow-auto whitespace-pre-wrap">
                                                        {item.responseBody || 'No response data'}
                                                    </div>
                                                </div>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}