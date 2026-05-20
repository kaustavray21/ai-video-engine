import React, { useState, useEffect, useCallback } from 'react';
import { Upload, Search, GitMerge, RefreshCw, FileArchive, CheckCircle, XCircle, Clock, Loader2, AlertTriangle, ChevronDown, ChevronRight, FolderOpen, Trash2 } from 'lucide-react';
import type { StudyMaterial, Course, StudyMaterialFile } from '../types';
import {
  uploadStudyMaterial,
  fetchStudyMaterials,
  fetchStudyMaterialStatus,
  queryStudyMaterial,
  queryStudyMaterialFile,
  mergeToCourse,
  fetchCourses,
  deleteStudyMaterial,
} from '../services/api';

export default function StudyMaterialsView() {
  const [materials, setMaterials] = useState<StudyMaterial[]>([]);
  const [courses, setCourses] = useState<Course[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);

  // Upload form
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [file, setFile] = useState<File | null>(null);

  // Query
  const [querySmId, setQuerySmId] = useState<number | null>(null);
  const [queryFileId, setQueryFileId] = useState<number | null>(null);
  const [queryQuestion, setQueryQuestion] = useState('');
  const [queryAnswer, setQueryAnswer] = useState('');
  const [querySources, setQuerySources] = useState<unknown[]>([]);
  const [retrievedSources, setRetrievedSources] = useState<Array<{source_file: string; file_type: string; chunk_index: number; chunk_role: string; score: number; header_context?: string; page_number?: number; function_name?: string}>>([]);
  const [sourcesExpanded, setSourcesExpanded] = useState(false);
  const [querying, setQuerying] = useState(false);

  // Files view
  const [expandedSmId, setExpandedSmId] = useState<number | null>(null);
  const [expandedSmFiles, setExpandedSmFiles] = useState<StudyMaterialFile[]>([]);
  const [loadingFiles, setLoadingFiles] = useState(false);

  // Merge
  const [mergeSmId, setMergeSmId] = useState<number | null>(null);
  const [mergeCourseId, setMergeCourseId] = useState('');
  const [mergeResult, setMergeResult] = useState('');
  const [merging, setMerging] = useState(false);

  const loadMaterials = useCallback(async () => {
    setLoading(true);
    const data = await fetchStudyMaterials();
    setMaterials(data);
    setLoading(false);
  }, []);

  const loadCourses = useCallback(async () => {
    const data = await fetchCourses();
    setCourses(data);
  }, []);

  useEffect(() => {
    loadMaterials();
    loadCourses();
  }, [loadMaterials, loadCourses]);

  // Polling for in-progress materials has been removed to stop constant backend requests.
  // Users will need to manually click the refresh button to see status updates.

  const handleUpload = async () => {
    if (!name.trim() || !file) return;
    setUploading(true);
    const result = await uploadStudyMaterial(name.trim(), file, description.trim() || undefined);
    if (result) {
      setName('');
      setDescription('');
      setFile(null);
      await loadMaterials();
    } else {
      alert('Upload failed. Check console for details.');
    }
    setUploading(false);
  };

  const handleExpandFiles = async (id: number) => {
    if (expandedSmId === id) {
      setExpandedSmId(null);
      setExpandedSmFiles([]);
      return;
    }
    setExpandedSmId(id);
    setLoadingFiles(true);
    const status = await fetchStudyMaterialStatus(id);
    if (status && status.files) {
      setExpandedSmFiles(status.files);
    } else {
      setExpandedSmFiles([]);
    }
    setLoadingFiles(false);
  };

  const handleQuery = async () => {
    if (!queryQuestion.trim()) return;
    if (querySmId === null && queryFileId === null) return;
    setQuerying(true);
    setQueryAnswer('');
    setQuerySources([]);
    setRetrievedSources([]);
    setSourcesExpanded(false);
    
    let result;
    if (queryFileId !== null) {
      result = await queryStudyMaterialFile(queryFileId, queryQuestion.trim());
    } else if (querySmId !== null) {
      result = await queryStudyMaterial(querySmId, queryQuestion.trim());
    }
    
    if (result) {
      setQueryAnswer(result.answer);
      setQuerySources(result.sources);
      if (result.retrieved_sources) {
        setRetrievedSources(result.retrieved_sources as typeof retrievedSources);
      }
    } else {
      setQueryAnswer('Query failed.');
    }
    setQuerying(false);
  };

  const handleMerge = async (smId: number) => {
    const cid = parseInt(mergeCourseId);
    if (!cid) return;
    setMerging(true);
    setMergeResult('');
    const result = await mergeToCourse(smId, cid);
    if (result) {
      setMergeResult(`Merged successfully. Path: ${result.merged_vectorstore_path}`);
      await loadMaterials();
    } else {
      setMergeResult('Merge failed or already merged.');
    }
    setMerging(false);
  };

  const handleDelete = async (sm: StudyMaterial) => {
    if (sm.attached_courses_count > 0) {
      alert('Cannot delete: This study material is attached to one or more courses. Please detach it first.');
      return;
    }
    if (!confirm(`Are you sure you want to permanently delete "${sm.name}" and all its files?`)) return;
    
    setLoading(true);
    const result = await deleteStudyMaterial(sm.id);
    if (result.success) {
      await loadMaterials();
    } else {
      alert(result.error);
    }
    setLoading(false);
  };

  const statusIcon = (status: string) => {
    switch (status) {
      case 'completed': return <CheckCircle className="w-4 h-4 text-green-400" />;
      case 'failed': return <XCircle className="w-4 h-4 text-red-400" />;
      case 'processing': return <Loader2 className="w-4 h-4 text-amber-400 animate-spin" />;
      default: return <Clock className="w-4 h-4 text-zinc-500" />;
    }
  };

  const statusColor = (status: string) => {
    switch (status) {
      case 'completed': return 'text-green-400';
      case 'failed': return 'text-red-400';
      case 'processing': return 'text-amber-400';
      default: return 'text-zinc-500';
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2 mb-2">
        <FileArchive className="w-5 h-5 text-[#f05a28]" />
        <h2 className="text-lg font-medium">Study Materials</h2>
      </div>

      {/* ── Upload Form ── */}
      <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl p-5">
        <h3 className="text-sm font-medium text-zinc-300 mb-4 flex items-center gap-2">
          <Upload className="w-4 h-4 text-[#f05a28]" />
          Upload New Study Material
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <input
            type="text"
            placeholder="Name (unique slug)"
            value={name}
            onChange={e => setName(e.target.value)}
            className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-[#f05a28]"
          />
          <input
            type="text"
            placeholder="Description (optional)"
            value={description}
            onChange={e => setDescription(e.target.value)}
            className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-[#f05a28]"
          />
          <div className="flex gap-2">
            <label className="flex-1 flex items-center gap-2 bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-400 cursor-pointer hover:border-zinc-500 transition-colors">
              <span className="truncate flex-1">{file ? file.name : 'Select .zip file...'}</span>
              <input
                type="file"
                accept=".zip"
                onChange={e => setFile(e.target.files?.[0] ?? null)}
                className="hidden"
              />
            </label>
            <button
              onClick={handleUpload}
              disabled={uploading || !name.trim() || !file}
              className="bg-[#f05a28] hover:bg-[#d4481c] disabled:bg-zinc-700 disabled:text-zinc-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
            >
              {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
              Upload
            </button>
          </div>
        </div>
        <p className="text-xs text-zinc-600 mt-2">Key: <code className="text-zinc-500">zip_file</code> (multipart/form-data)</p>
      </div>

      {/* ── Materials List ── */}
      <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-medium text-zinc-300 flex items-center gap-2">
            <FileArchive className="w-4 h-4 text-[#f05a28]" />
            All Study Materials
          </h3>
          <button onClick={loadMaterials} disabled={loading} className="text-zinc-500 hover:text-white transition-colors">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>

        {materials.length === 0 ? (
          <p className="text-zinc-600 text-sm py-4 text-center">No study materials yet. Upload one above.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-zinc-500 border-b border-zinc-800">
                  <th className="text-left py-2 px-2 font-medium">ID</th>
                  <th className="text-left py-2 px-2 font-medium">Name</th>
                  <th className="text-left py-2 px-2 font-medium">Status</th>
                  <th className="text-left py-2 px-2 font-medium">Files</th>
                  <th className="text-left py-2 px-2 font-medium">Courses</th>
                  <th className="text-left py-2 px-2 font-medium">Created</th>
                  <th className="text-right py-2 px-2 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {materials.map(sm => (
                  <React.Fragment key={sm.id}>
                  <tr className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                    <td className="py-2 px-2 text-zinc-400">{sm.id}</td>
                    <td className="py-2 px-2 text-zinc-100 font-medium">{sm.name}</td>
                    <td className={`py-2 px-2 flex items-center gap-1.5 ${statusColor(sm.status)}`}>
                      {statusIcon(sm.status)}
                      <span className="capitalize">{sm.status}</span>
                      {sm.status === 'failed' && sm.error_log && (
                        <span className="relative group">
                          <AlertTriangle className="w-3.5 h-3.5 text-red-400 cursor-help" />
                          <span className="absolute bottom-full left-0 mb-1 hidden group-hover:block bg-zinc-900 border border-zinc-700 text-xs text-red-300 px-2 py-1 rounded shadow-lg max-w-xs whitespace-pre-wrap z-10">
                            {sm.error_log}
                          </span>
                        </span>
                      )}
                    </td>
                    <td className="py-2 px-2 text-zinc-400">{sm.files_count}</td>
                    <td className="py-2 px-2 text-zinc-400">{sm.attached_courses_count}</td>
                    <td className="py-2 px-2 text-zinc-400 text-xs">{new Date(sm.created_at).toLocaleDateString()}</td>
                    <td className="py-2 px-2 text-right space-x-1">
                      {sm.status === 'completed' && (
                        <>
                          <button
                            onClick={() => { setQuerySmId(sm.id); setQueryAnswer(''); setQuerySources([]); setQueryQuestion(''); }}
                            className="text-zinc-400 hover:text-white p-1.5 rounded hover:bg-zinc-800 transition-colors"
                            title="Query"
                          >
                            <Search className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => { setMergeSmId(sm.id); setMergeResult(''); }}
                            className="text-zinc-400 hover:text-white p-1.5 rounded hover:bg-zinc-800 transition-colors"
                            title="Merge to Course"
                          >
                            <GitMerge className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => handleExpandFiles(sm.id)}
                            className={`p-1.5 rounded transition-colors ${expandedSmId === sm.id ? 'text-white bg-zinc-700' : 'text-zinc-400 hover:text-white hover:bg-zinc-800'}`}
                            title="View Files"
                          >
                            <FolderOpen className="w-4 h-4" />
                          </button>
                        </>
                      )}
                      <button
                        onClick={() => handleDelete(sm)}
                        className="text-zinc-400 hover:text-red-400 p-1.5 rounded hover:bg-zinc-800 transition-colors"
                        title="Delete"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                  {expandedSmId === sm.id && (
                    <tr className="bg-zinc-900/30 border-b border-zinc-800/50">
                      <td colSpan={7} className="px-6 py-4">
                        <div className="flex items-center justify-between mb-3">
                          <h4 className="text-sm font-medium text-zinc-300">Files in {sm.name}</h4>
                          <button onClick={() => setExpandedSmId(null)} className="text-zinc-500 hover:text-white text-xs">Close</button>
                        </div>
                        {loadingFiles ? (
                          <div className="flex items-center gap-2 text-zinc-400 text-sm py-2">
                            <Loader2 className="w-4 h-4 animate-spin" /> Loading files...
                          </div>
                        ) : expandedSmFiles.length === 0 ? (
                          <p className="text-zinc-500 text-sm">No files found.</p>
                        ) : (
                          <div className="bg-zinc-900 border border-zinc-800 rounded-lg overflow-hidden">
                            <table className="w-full text-xs">
                              <thead className="bg-zinc-800/50 text-zinc-400">
                                <tr>
                                  <th className="text-left py-2 px-3 font-medium">File ID</th>
                                  <th className="text-left py-2 px-3 font-medium">Name</th>
                                  <th className="text-left py-2 px-3 font-medium">Type</th>
                                  <th className="text-left py-2 px-3 font-medium">Status</th>
                                  <th className="text-left py-2 px-3 font-medium">Chunks</th>
                                  <th className="text-right py-2 px-3 font-medium">Query</th>
                                </tr>
                              </thead>
                              <tbody className="divide-y divide-zinc-800">
                                {expandedSmFiles.map(f => (
                                  <tr key={f.file_id} className="hover:bg-zinc-800/30">
                                    <td className="py-2 px-3 text-zinc-500">{f.file_id}</td>
                                    <td className="py-2 px-3 text-zinc-300 font-medium">{f.original_name}</td>
                                    <td className="py-2 px-3 text-zinc-500">{f.file_type}</td>
                                    <td className={`py-2 px-3 flex items-center gap-1.5 ${statusColor(f.status)}`}>
                                      {statusIcon(f.status)}
                                      <span className="capitalize">{f.status}</span>
                                      {f.status === 'failed' && f.error && (
                                        <span className="relative group">
                                          <AlertTriangle className="w-3.5 h-3.5 text-red-400 cursor-help" />
                                          <span className="absolute bottom-full left-0 mb-1 hidden group-hover:block bg-zinc-950 border border-zinc-700 text-xs text-red-300 px-2 py-1 rounded shadow-lg max-w-xs whitespace-pre-wrap z-10">
                                            {f.error}
                                          </span>
                                        </span>
                                      )}
                                    </td>
                                    <td className="py-2 px-3 text-zinc-500">{f.chunk_count}</td>
                                    <td className="py-2 px-3 text-right">
                                      {f.status === 'completed' && (
                                        <button
                                          onClick={() => { setQueryFileId(f.file_id); setQuerySmId(null); setQueryAnswer(''); setQuerySources([]); setQueryQuestion(''); }}
                                          className="text-zinc-400 hover:text-white p-1 rounded hover:bg-zinc-700 transition-colors"
                                          title="Query this File"
                                        >
                                          <Search className="w-3.5 h-3.5" />
                                        </button>
                                      )}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        )}
                      </td>
                    </tr>
                  )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Query Panel ── */}
      {(querySmId !== null || queryFileId !== null) && (
        <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-zinc-300 flex items-center gap-2">
              <Search className="w-4 h-4 text-[#f05a28]" />
              Query: {querySmId !== null 
                ? materials.find(m => m.id === querySmId)?.name 
                : expandedSmFiles.find(f => f.file_id === queryFileId)?.original_name || `File #${queryFileId}`}
            </h3>
            <button onClick={() => { setQuerySmId(null); setQueryFileId(null); }} className="text-zinc-500 hover:text-white text-xs">Close</button>
          </div>
          <div className="flex gap-2">
            <input
              type="text"
              placeholder={querySmId !== null ? "Ask a question about this study material..." : "Ask a question about this file..."}
              value={queryQuestion}
              onChange={e => setQueryQuestion(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleQuery()}
              className="flex-1 bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-[#f05a28]"
            />
            <button
              onClick={handleQuery}
              disabled={querying || !queryQuestion.trim()}
              className="bg-[#f05a28] hover:bg-[#d4481c] disabled:bg-zinc-700 disabled:text-zinc-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
            >
              {querying ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Ask'}
            </button>
          </div>
          {queryAnswer && (
            <div className="mt-3 p-3 bg-zinc-800 rounded-lg">
              <p className="text-sm text-zinc-300 whitespace-pre-wrap">{queryAnswer}</p>
              {querySources.length > 0 && (
                <p className="text-xs text-zinc-600 mt-2">
                  Sources: {querySources.length} chunks
                </p>
              )}
              {retrievedSources.length > 0 && (
                <div className="mt-3 border-t border-zinc-700 pt-2">
                  <button
                    onClick={() => setSourcesExpanded(!sourcesExpanded)}
                    className="flex items-center gap-1 text-xs text-zinc-400 hover:text-zinc-200 transition-colors"
                  >
                    {sourcesExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                    Retrieved Sources ({retrievedSources.length})
                  </button>
                  {sourcesExpanded && (
                    <div className="mt-2 space-y-1.5">
                      {retrievedSources.map((src, idx) => (
                        <div key={idx} className="flex items-center gap-2 text-xs py-1 px-2 bg-zinc-900 rounded">
                          <span className="font-medium text-zinc-200 truncate max-w-[200px]" title={src.source_file}>
                            {src.source_file || 'Unknown'}
                          </span>
                          <span className="px-1.5 py-0.5 rounded bg-zinc-700 text-zinc-400">
                            {src.file_type || '?'}
                          </span>
                          <span className="text-zinc-500">score: {src.score?.toFixed(2)}</span>
                          {src.page_number && <span className="text-zinc-500">p.{src.page_number}</span>}
                          {src.function_name && <span className="text-zinc-500 font-mono">{src.function_name}()</span>}
                          {src.header_context && <span className="text-zinc-500 italic truncate max-w-[150px]" title={src.header_context}>{src.header_context}</span>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Merge Panel ── */}
      {mergeSmId !== null && (
        <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-zinc-300 flex items-center gap-2">
              <GitMerge className="w-4 h-4 text-[#f05a28]" />
              Merge: {materials.find(m => m.id === mergeSmId)?.name}
            </h3>
            <button onClick={() => setMergeSmId(null)} className="text-zinc-500 hover:text-white text-xs">Close</button>
          </div>
          <div className="flex gap-2">
            <select
              value={mergeCourseId}
              onChange={e => setMergeCourseId(e.target.value)}
              className="flex-1 bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:border-[#f05a28]"
            >
              <option value="">Select a course...</option>
              {courses.map(c => (
                <option key={c.id} value={c.id}>{c.title} (ID: {c.id})</option>
              ))}
            </select>
            <button
              onClick={() => handleMerge(mergeSmId)}
              disabled={merging || !mergeCourseId}
              className="bg-[#f05a28] hover:bg-[#d4481c] disabled:bg-zinc-700 disabled:text-zinc-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
            >
              {merging ? <Loader2 className="w-4 h-4 animate-spin" /> : <GitMerge className="w-4 h-4" />}
              Merge
            </button>
          </div>
          {mergeResult && (
            <p className="mt-2 text-sm text-zinc-400">{mergeResult}</p>
          )}
        </div>
      )}
    </div>
  );
}
