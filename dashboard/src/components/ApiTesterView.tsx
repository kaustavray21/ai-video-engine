import { useState, useRef, useEffect } from 'react';
import { Play, Globe, Plus, X, Database, ChevronDown, Trash2 } from 'lucide-react';
import { sendRequest, logApiCall, saveLogEntry } from '../services/api';
import { API_ENDPOINTS, COMMON_HEADERS } from '../constants/endpoints';
import type { HeaderItem } from '../types';

// ── HTTP methods & colour map ────────────────────────────────────────────────
const HTTP_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'];

const METHOD_COLORS: Record<string, { text: string; bg: string; border: string }> = {
  GET:     { text: 'text-emerald-400', bg: 'bg-emerald-400/10',  border: 'border-emerald-400/30' },
  POST:    { text: 'text-[#f05a28]',   bg: 'bg-[#f05a28]/10',   border: 'border-[#f05a28]/30'   },
  PUT:     { text: 'text-blue-400',    bg: 'bg-blue-400/10',     border: 'border-blue-400/30'    },
  PATCH:   { text: 'text-amber-400',   bg: 'bg-amber-400/10',    border: 'border-amber-400/30'   },
  DELETE:  { text: 'text-red-400',     bg: 'bg-red-400/10',      border: 'border-red-400/30'     },
  HEAD:    { text: 'text-purple-400',  bg: 'bg-purple-400/10',   border: 'border-purple-400/30'  },
  OPTIONS: { text: 'text-zinc-400',    bg: 'bg-zinc-400/10',     border: 'border-zinc-700'       },
};

const BASE_URL = '/api';
const DEFAULT_IDX = 0;

const initialState = () => ({
  selectedIdx:    DEFAULT_IDX,
  selectedMethod: API_ENDPOINTS[DEFAULT_IDX].method,
  fullUrl:        BASE_URL + API_ENDPOINTS[DEFAULT_IDX].path,
  requestBody:    API_ENDPOINTS[DEFAULT_IDX].bodyHint,
  headersList:    [{ key: 'Content-Type', value: 'application/json' }] as HeaderItem[],
  responseBody:   '',
  statusText:     '',
  statusCode:     '' as number | string,
  lastLogId:      null as number | null,
  saveMsg:        '',
});

type BodyType = 'none' | 'form-data' | 'x-www-form-urlencoded' | 'raw' | 'binary' | 'GraphQL';

type FormDataItem = {
  id: string;
  enabled: boolean;
  key: string;
  type: 'Text' | 'File';
  value: string;
  file: File | null;
  description: string;
};

// ── Component ────────────────────────────────────────────────────────────────
export default function ApiTesterView() {
  const s = initialState();

  const [selectedIdx,    setSelectedIdx]    = useState(s.selectedIdx);
  const [selectedMethod, setSelectedMethod] = useState(s.selectedMethod);
  const [fullUrl,        setFullUrl]        = useState(s.fullUrl);
  const [requestBody,    setRequestBody]    = useState(s.requestBody);
  const [headersList,    setHeadersList]    = useState<HeaderItem[]>(s.headersList);
  const [responseBody,   setResponseBody]   = useState(s.responseBody);
  const [statusText,     setStatusText]     = useState(s.statusText);
  const [statusCode,     setStatusCode]     = useState<number | string>(s.statusCode);
  const [isLoading,      setIsLoading]      = useState(false);
  const [bodyType,       setBodyType]       = useState<BodyType>('raw');
  const [formDataList,   setFormDataList]   = useState<FormDataItem[]>([
    { id: Math.random().toString(), enabled: true, key: '', type: 'Text', value: '', file: null, description: '' }
  ]);
  const [lastLogId,      setLastLogId]      = useState<number | null>(s.lastLogId);
  const [saveMsg,        setSaveMsg]        = useState(s.saveMsg);

  // dropdown visibility
  const [showMethodDrop,  setShowMethodDrop]  = useState(false);
  const [openHeaderIdx,   setOpenHeaderIdx]   = useState<number | null>(null);

  const methodDropRef  = useRef<HTMLDivElement>(null);
  const headersDropRef = useRef<HTMLDivElement>(null);

  // Close dropdowns on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (methodDropRef.current  && !methodDropRef.current.contains(e.target as Node))
        setShowMethodDrop(false);
      if (headersDropRef.current && !headersDropRef.current.contains(e.target as Node))
        setOpenHeaderIdx(null);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // ── Handlers ──────────────────────────────────────────────────────────────

  /** Right-side endpoint dropdown changed → sync URL + method into left side. */
  const handleEndpointChange = (idx: number) => {
    const ep = API_ENDPOINTS[idx];
    setSelectedIdx(idx);
    setSelectedMethod(ep.method);
    setFullUrl(BASE_URL + ep.path);
    setRequestBody(ep.bodyHint);
    // clear previous response
    setResponseBody('');
    setStatusText('');
    setStatusCode('');
    setLastLogId(null);
    setSaveMsg('');
  };

  /** Reset everything back to defaults. */
  const handleClear = () => {
    const ep = API_ENDPOINTS[DEFAULT_IDX];
    setSelectedIdx(DEFAULT_IDX);
    setSelectedMethod(ep.method);
    setFullUrl(BASE_URL + ep.path);
    setRequestBody(ep.bodyHint);
    setHeadersList([{ key: 'Content-Type', value: 'application/json' }]);
    setResponseBody('');
    setStatusText('');
    setStatusCode('');
    setLastLogId(null);
    setSaveMsg('');
  };

  /** Send request. */
  const handleSend = async () => {
    setIsLoading(true);
    setResponseBody('');
    setStatusText('');
    setStatusCode('');
    setLastLogId(null);
    setSaveMsg('');

    const customHeaders: Record<string, string> = {};
    headersList.forEach((h) => { if (h.key.trim()) customHeaders[h.key.trim()] = h.value; });

    let finalBody: string | FormData | undefined;
    if (bodyType === 'raw') {
      finalBody = requestBody;
    } else if (bodyType === 'form-data') {
      const fd = new FormData();
      formDataList.forEach(item => {
        if (item.enabled && item.key.trim()) {
          if (item.type === 'Text') {
            fd.append(item.key.trim(), item.value);
          } else if (item.type === 'File' && item.file) {
            fd.append(item.key.trim(), item.file);
          }
        }
      });
      finalBody = fd;
    }

    const res = await sendRequest(fullUrl, selectedMethod, finalBody, customHeaders);

    setStatusCode(res.status);
    setStatusText(res.statusText);
    const resStr = typeof res.data === 'string' ? res.data : JSON.stringify(res.data, null, 2);
    setResponseBody(resStr);
    setIsLoading(false);

    // Auto-log (bodies truncated to keep DB lean)
    const logRes = await logApiCall({
      method:        selectedMethod,
      endpoint:      fullUrl,
      request_body:  requestBody.slice(0, 500),
      response_body: resStr.slice(0, 500),
      status_code:   res.status,
      status_text:   res.statusText,
      latency_ms:    res.latencyMs,
    });
    if (logRes) setLastLogId(logRes.id);
  };

  const handleSave = async () => {
    if (!lastLogId) return;
    const ok = await saveLogEntry(lastLogId);
    setSaveMsg(ok ? '✓ Saved to history' : 'Failed to save');
    setTimeout(() => setSaveMsg(''), 2000);
  };

  const mc = METHOD_COLORS[selectedMethod] ?? METHOD_COLORS.OPTIONS;

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="max-w-[1200px] mx-auto flex flex-col gap-6">

      {/* ── Request Builder ── */}
      <div className="bg-[#0a0a0a] rounded-xl border border-zinc-900 p-6">

        {/* ── URL bar ── */}
        <div className="flex flex-col md:flex-row gap-3 mb-6">

          {/* BOX 1 — Method pill + full URL input */}
          <div className="flex flex-1 bg-[#0f0f0f] rounded-lg border border-zinc-800 overflow-visible min-w-0">

            {/* Method dropdown */}
            <div className="relative flex-shrink-0" ref={methodDropRef}>
              <button
                type="button"
                onClick={() => setShowMethodDrop(!showMethodDrop)}
                className={`
                  flex items-center gap-1.5 px-3 h-full
                  border-r border-zinc-800
                  hover:bg-zinc-900/70 transition-colors cursor-pointer
                  rounded-l-lg
                  ${mc.text}
                `}
              >
                <span className={`text-[11px] font-extrabold tracking-widest px-1.5 py-0.5 rounded ${mc.bg}`}>
                  {selectedMethod}
                </span>
                <ChevronDown className={`w-3 h-3 opacity-50 transition-transform ${showMethodDrop ? 'rotate-180' : ''}`} />
              </button>

              {showMethodDrop && (
                <div className="absolute z-50 top-full left-0 mt-1.5 w-36 bg-[#111] border border-zinc-700 rounded-lg shadow-2xl overflow-hidden">
                  {HTTP_METHODS.map((m) => {
                    const c = METHOD_COLORS[m] ?? METHOD_COLORS.OPTIONS;
                    return (
                      <button
                        key={m}
                        type="button"
                        onClick={() => { setSelectedMethod(m); setShowMethodDrop(false); }}
                        className={`
                          w-full flex items-center gap-2 px-3 py-2.5 text-xs font-bold tracking-wider
                          transition-colors hover:bg-zinc-800 cursor-pointer
                          ${selectedMethod === m ? 'bg-zinc-800' : ''}
                        `}
                      >
                        <span className={`${c.text} ${c.bg} px-1.5 py-0.5 rounded text-[10px] font-extrabold tracking-widest`}>
                          {m}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Full URL input — syncs with right-side endpoint picker, also freely editable */}
            <input
              type="text"
              value={fullUrl}
              onChange={(e) => setFullUrl(e.target.value)}
              placeholder="http://127.0.0.1:8000/api/..."
              className="
                flex-1 min-w-0 bg-transparent px-3 py-2.5
                text-sm text-zinc-100 font-mono outline-none
                placeholder:text-zinc-600
              "
            />
          </div>

          {/* BOX 2 — Endpoint label dropdown (fills Box 1 when changed) */}
          <div className="flex bg-[#0f0f0f] rounded-lg border border-zinc-800 min-w-[260px] max-w-xs">
            <div className="flex-1 flex items-center px-3">
              <Globe className="w-4 h-4 text-zinc-500 mr-2 flex-shrink-0" />
              <select
                value={selectedIdx}
                onChange={(e) => handleEndpointChange(Number(e.target.value))}
                className="w-full bg-transparent py-2.5 outline-none text-zinc-100 cursor-pointer text-sm"
              >
                {API_ENDPOINTS.map((ep, i) => (
                  <option key={i} value={i} className="bg-[#111]">
                    {ep.label} — {ep.path}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Send + Clear buttons */}
          <div className="flex gap-2 flex-shrink-0">
            <button
              onClick={handleSend}
              disabled={isLoading}
              className="
                bg-[#f05a28] hover:bg-[#d4481c] text-white
                px-6 py-2.5 rounded-lg font-medium transition-colors
                flex items-center gap-2 justify-center shadow-sm
                disabled:opacity-70 disabled:cursor-not-allowed whitespace-nowrap
              "
            >
              <Play className="w-4 h-4" />
              {isLoading ? 'Sending…' : 'Send'}
            </button>

            <button
              onClick={handleClear}
              title="Clear all fields"
              className="
                bg-zinc-900 border border-zinc-700
                hover:border-red-500/60 hover:bg-red-500/10
                text-zinc-400 hover:text-red-400
                px-3 py-2.5 rounded-lg transition-all
                flex items-center justify-center gap-1.5
              "
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* ── Headers ── */}
        <div className="mb-6">
          <div className="flex justify-between items-center mb-3">
            <label className="block text-sm font-medium text-zinc-300">Headers</label>
            <button
              onClick={() => setHeadersList([...headersList, { key: '', value: '' }])}
              className="text-sm text-[#f05a28] hover:text-[#d4481c] flex items-center gap-1 font-medium"
            >
              <Plus className="w-4 h-4" />
              Add Header
            </button>
          </div>

          <div className="space-y-2" ref={headersDropRef}>
            {headersList.map((header, index) => (
              <div key={index} className="flex gap-2 items-center">
                {/* Header key dropdown */}
                <div className="flex-1 relative">
                  <button
                    type="button"
                    onClick={() => setOpenHeaderIdx(openHeaderIdx === index ? null : index)}
                    className="
                      w-full flex items-center justify-between
                      bg-[#0f0f0f] border border-zinc-800 rounded-md px-3 py-2
                      text-sm text-left outline-none
                      hover:border-zinc-600 focus:border-[#f05a28] transition-colors cursor-pointer
                    "
                  >
                    <span className={header.key ? 'text-zinc-100' : 'text-zinc-500'}>
                      {header.key || 'Select Header'}
                    </span>
                    <ChevronDown className={`w-4 h-4 text-zinc-500 transition-transform ${openHeaderIdx === index ? 'rotate-180' : ''}`} />
                  </button>

                  {openHeaderIdx === index && (
                    <div
                      className="absolute z-50 top-full left-0 mt-1 w-full bg-[#111] border border-zinc-700 rounded-lg shadow-2xl max-h-60 overflow-y-auto"
                      style={{ scrollbarWidth: 'thin', scrollbarColor: '#333 #111' }}
                    >
                      {COMMON_HEADERS.map((h) => (
                        <div
                          key={h}
                          onClick={() => {
                            const newH = [...headersList];
                            newH[index].key = h;
                            setHeadersList(newH);
                            setOpenHeaderIdx(null);
                          }}
                          className={`
                            px-4 py-2.5 text-sm cursor-pointer transition-colors
                            ${header.key === h
                              ? 'bg-[#f05a28] text-white font-medium'
                              : 'text-zinc-300 hover:bg-[#f05a28] hover:text-white'
                            }
                          `}
                        >
                          {h}
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <input
                  type="text"
                  value={header.value}
                  onChange={(e) => {
                    const newH = [...headersList];
                    newH[index].value = e.target.value;
                    setHeadersList(newH);
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
              <div className="text-sm text-zinc-600 italic py-2">No headers configured.</div>
            )}
          </div>
        </div>

        {/* ── Body ── */}
        <div>
          <div className="flex items-center gap-4 mb-3 text-sm">
            <span className="font-medium text-zinc-300">Body</span>
            <div className="flex flex-wrap items-center gap-4">
              {(['none', 'form-data', 'x-www-form-urlencoded', 'raw', 'binary', 'GraphQL'] as BodyType[]).map(type => (
                <label key={type} className="flex items-center gap-1.5 cursor-pointer text-zinc-400 hover:text-zinc-200">
                  <input
                    type="radio"
                    name="bodyType"
                    value={type}
                    checked={bodyType === type}
                    onChange={(e) => setBodyType(e.target.value as BodyType)}
                    className="accent-[#f05a28]"
                  />
                  {type}
                </label>
              ))}
            </div>
          </div>

          {bodyType === 'raw' && (
            <textarea
              value={requestBody}
              onChange={(e) => setRequestBody(e.target.value)}
              placeholder={'{\n  "key": "value"\n}'}
              className="
                w-full h-40 bg-[#0f0f0f] text-zinc-300 p-4
                rounded-lg border border-zinc-800 font-mono text-sm
                outline-none focus:border-[#f05a28]
                resize-y placeholder:text-zinc-700
              "
            />
          )}

          {bodyType === 'form-data' && (
            <div className="border border-zinc-800 rounded-lg overflow-x-auto bg-[#0f0f0f]">
              <div className="min-w-[600px]">
                <div className="grid grid-cols-[auto_minmax(150px,1fr)_auto_minmax(200px,1fr)_minmax(150px,1fr)_auto] gap-2 p-2 border-b border-zinc-800 bg-zinc-900/50 text-xs font-medium text-zinc-400">
                  <div className="w-6"></div>
                  <div>Key</div>
                  <div></div>
                  <div>Value</div>
                  <div>Description</div>
                  <div className="w-8"></div>
                </div>
                {formDataList.map((item, index) => (
                  <div key={item.id} className="grid grid-cols-[auto_minmax(150px,1fr)_auto_minmax(200px,1fr)_minmax(150px,1fr)_auto] gap-2 p-2 items-center border-b border-zinc-800/50 last:border-0 hover:bg-zinc-800/20">
                    <div className="flex justify-center w-6">
                      <input
                        type="checkbox"
                        checked={item.enabled}
                        onChange={(e) => {
                          const next = [...formDataList];
                          next[index].enabled = e.target.checked;
                          setFormDataList(next);
                        }}
                        className="accent-[#f05a28] w-3.5 h-3.5"
                      />
                    </div>
                    <input
                      type="text"
                      value={item.key}
                      placeholder="Key"
                      onChange={(e) => {
                        const next = [...formDataList];
                        next[index].key = e.target.value;
                        if (index === formDataList.length - 1 && e.target.value) {
                          next.push({ id: Math.random().toString(), enabled: true, key: '', type: 'Text', value: '', file: null, description: '' });
                        }
                        setFormDataList(next);
                      }}
                      className="bg-transparent text-sm text-zinc-100 outline-none placeholder:text-zinc-600 w-full"
                    />
                    <div className="relative">
                      <select
                        value={item.type}
                        onChange={(e) => {
                          const next = [...formDataList];
                          next[index].type = e.target.value as 'Text' | 'File';
                          next[index].value = '';
                          next[index].file = null;
                          setFormDataList(next);
                        }}
                        className="bg-transparent text-xs text-zinc-400 outline-none cursor-pointer appearance-none pr-4"
                      >
                        <option value="Text" className="bg-[#111]">Text</option>
                        <option value="File" className="bg-[#111]">File</option>
                      </select>
                      <ChevronDown className="w-3 h-3 text-zinc-500 absolute right-0 top-1/2 -translate-y-1/2 pointer-events-none" />
                    </div>
                    <div className="min-w-0">
                      {item.type === 'Text' ? (
                        <input
                          type="text"
                          value={item.value}
                          placeholder="Value"
                          onChange={(e) => {
                            const next = [...formDataList];
                            next[index].value = e.target.value;
                            if (index === formDataList.length - 1 && e.target.value) {
                              next.push({ id: Math.random().toString(), enabled: true, key: '', type: 'Text', value: '', file: null, description: '' });
                            }
                            setFormDataList(next);
                          }}
                          className="bg-transparent text-sm text-zinc-100 outline-none placeholder:text-zinc-600 w-full"
                        />
                      ) : (
                        <label className="flex items-center cursor-pointer w-full group h-full py-1">
                          <input
                            type="file"
                            className="hidden"
                            onChange={(e) => {
                              const file = e.target.files?.[0] || null;
                              const next = [...formDataList];
                              next[index].file = file;
                              if (index === formDataList.length - 1 && file) {
                                next.push({ id: Math.random().toString(), enabled: true, key: '', type: 'Text', value: '', file: null, description: '' });
                              }
                              setFormDataList(next);
                              // Reset input value so same file can be re-selected if removed
                              e.target.value = '';
                            }}
                          />
                          {item.file ? (
                            <span className="text-sm text-zinc-100 bg-[#f05a28]/20 border border-[#f05a28]/30 px-2 py-0.5 rounded truncate max-w-full inline-block group-hover:bg-[#f05a28]/30 transition-colors">
                              {item.file.name}
                            </span>
                          ) : (
                            <span className="text-sm text-zinc-600 group-hover:text-zinc-400 transition-colors">
                              Select files
                            </span>
                          )}
                        </label>
                      )}
                    </div>
                    <input
                      type="text"
                      value={item.description}
                      placeholder="Description"
                      onChange={(e) => {
                        const next = [...formDataList];
                        next[index].description = e.target.value;
                        setFormDataList(next);
                      }}
                      className="bg-transparent text-sm text-zinc-100 outline-none placeholder:text-zinc-600 w-full"
                    />
                    <div className="flex justify-center w-8">
                      {index !== formDataList.length - 1 && (
                        <button
                          onClick={() => {
                            const next = [...formDataList];
                            next.splice(index, 1);
                            setFormDataList(next);
                          }}
                          className="text-zinc-500 hover:text-red-400 p-1 rounded transition-colors"
                        >
                          <X className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {bodyType !== 'raw' && bodyType !== 'form-data' && (
            <div className="h-40 bg-[#0f0f0f] border border-zinc-800 rounded-lg flex items-center justify-center text-sm text-zinc-600">
              This body type is not implemented in this demo.
            </div>
          )}
        </div>
      </div>

      {/* ── Response ── */}
      <div className="bg-[#0a0a0a] rounded-xl border border-zinc-900 p-6 flex-1 flex flex-col min-h-[300px]">
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-4 gap-4 border-b border-zinc-900 pb-4">
          <h2 className="text-sm font-medium text-zinc-100">Response Body</h2>

          <div className="flex flex-wrap items-center gap-3">
            {statusCode !== '' && (
              <div className="flex items-center gap-2 bg-[#0f0f0f] px-3 py-1.5 rounded-lg border border-zinc-800">
                <span className="text-xs text-zinc-500 font-medium">Status:</span>
                <span
                  className={`text-xs font-bold ${
                    typeof statusCode === 'number' && statusCode >= 200 && statusCode < 300
                      ? 'text-emerald-400'
                      : 'text-red-400'
                  }`}
                >
                  {statusCode} {statusText}
                </span>
              </div>
            )}

            {saveMsg && <span className="text-xs text-emerald-400">{saveMsg}</span>}

            <button
              onClick={handleSave}
              disabled={!lastLogId}
              className="
                bg-[#f05a28] hover:bg-[#d4481c] text-white
                px-4 py-1.5 rounded-lg font-medium transition-colors
                flex items-center gap-2 shadow-sm
                disabled:opacity-50 disabled:cursor-not-allowed text-xs
              "
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
          className="
            w-full flex-1 bg-[#0f0f0f] text-emerald-400 p-4
            rounded-lg border border-zinc-800 font-mono text-sm
            outline-none resize-none min-h-[250px] placeholder:text-zinc-700
          "
        />
      </div>
    </div>
  );
}
