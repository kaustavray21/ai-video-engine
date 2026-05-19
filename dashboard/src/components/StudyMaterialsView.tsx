import { useState, useEffect, useCallback } from 'react';
import { Upload, Search, GitMerge, RefreshCw, FileArchive, CheckCircle, XCircle, Clock, Loader2 } from 'lucide-react';
import type { StudyMaterial, Course } from '../types';
import {
  uploadStudyMaterial,
  fetchStudyMaterials,
  fetchStudyMaterialStatus,
  queryStudyMaterial,
  mergeToCourse,
  fetchCourses,
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
  const [queryQuestion, setQueryQuestion] = useState('');
  const [queryAnswer, setQueryAnswer] = useState('');
  const [querySources, setQuerySources] = useState<unknown[]>([]);
  const [querying, setQuerying] = useState(false);

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

  const handleQuery = async (id: number) => {
    if (!queryQuestion.trim()) return;
    setQuerying(true);
    setQueryAnswer('');
    setQuerySources([]);
    const result = await queryStudyMaterial(id, queryQuestion.trim());
    if (result) {
      setQueryAnswer(result.answer);
      setQuerySources(result.sources);
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
                  <tr key={sm.id} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                    <td className="py-2 px-2 text-zinc-400">{sm.id}</td>
                    <td className="py-2 px-2 text-zinc-100 font-medium">{sm.name}</td>
                    <td className={`py-2 px-2 flex items-center gap-1.5 ${statusColor(sm.status)}`}>
                      {statusIcon(sm.status)}
                      <span className="capitalize">{sm.status}</span>
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
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Query Panel ── */}
      {querySmId !== null && (
        <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-zinc-300 flex items-center gap-2">
              <Search className="w-4 h-4 text-[#f05a28]" />
              Query: {materials.find(m => m.id === querySmId)?.name}
            </h3>
            <button onClick={() => setQuerySmId(null)} className="text-zinc-500 hover:text-white text-xs">Close</button>
          </div>
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="Ask a question about this study material..."
              value={queryQuestion}
              onChange={e => setQueryQuestion(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleQuery(querySmId)}
              className="flex-1 bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-[#f05a28]"
            />
            <button
              onClick={() => handleQuery(querySmId)}
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
