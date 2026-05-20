"""
VectorStore manager — load, query, and test FAISS vectorstores.

Supports hybrid BM25+FAISS retrieval via RRF, parent-child chunk
expansion, and per-chunk source attribution.
"""

import os
import re
import logging
import pickle
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_core.prompts import PromptTemplate

logger = logging.getLogger(__name__)

RRF_K = 60  # Standard RRF constant


@dataclass
class QueryResult:
    success: bool
    answer: str = ''
    source_chunks: int = 0
    error: str = ''
    retrieved_sources: List[dict] = field(default_factory=list)
    retrieved_chunk_count: int = 0


QA_PROMPT_MIXED = PromptTemplate(
    template="""You are an AI tutor helping students understand course content.

Course: {course_title}
Video: {video_title}

INSTRUCTIONS:
1. Answer ONLY using the context provided below. Do not use prior knowledge.
2. When citing information, reference the source file name if available in the context metadata.
3. If the provided context does not contain information about the topic, respond with:
   "The provided context does not contain information about this topic."
4. If the context contains chunks from both video transcripts and study materials,
   separate your answer into:
   **From video:** (information from video transcript chunks)
   **From study materials:** (information from study material chunks)
5. Be concise and clear.

Context:
{context}

Question: {question}

Answer:""",
    input_variables=['context', 'question', 'course_title', 'video_title'],
)


QA_PROMPT_SM = PromptTemplate(
    template="""You are an AI tutor helping students understand study material content.

Study Material: {course_title}

INSTRUCTIONS:
1. Answer ONLY using the context provided below. Do not use prior knowledge.
2. Reference each source file by its name (shown in [Source: ...] annotations).
3. If the provided context does not contain information about the topic, respond with:
   "The provided context does not contain information about this topic."
4. When asked about topics, overview, or what the study material contains,
   list every distinct file/topic visible in the source annotations with a brief
   description of what each file covers.
5. Be concise and clear. Do NOT mention "video" or "video transcript" — this is study material only.

Context:
{context}

Question: {question}

Answer:""",
    input_variables=['context', 'question', 'course_title'],
)

# Keep backward compat alias
QA_PROMPT = QA_PROMPT_MIXED

# Overview question patterns — trigger broader retrieval
OVERVIEW_PATTERNS = [
    'what are the topics', 'what topics', 'list the topics', 'list all',
    'what files', 'what is in this', 'overview', 'summarize all',
    'what does this contain', 'what is covered', 'what are the contents',
    'table of contents', 'describe the study material', 'what subjects',
    'what are the files', 'list the files', 'what courses', 'what subjects',
    'what do you have', 'show me the files', 'what material',
]

# Max guaranteed slots in overview — small files filled first, large files capped
OVERVIEW_MAX_GUARANTEED_FILES = 15


class VectorStoreManager:
    """Load, query, and test FAISS vectorstores with hybrid search."""

    def __init__(self, openai_api_key: str):
        self.embeddings = OpenAIEmbeddings(openai_api_key=openai_api_key)
        self.llm = ChatOpenAI(
            model_name='gpt-4o-mini',
            temperature=0.3,
            max_tokens=1000,
            openai_api_key=openai_api_key,
        )

    def load(self, path: str) -> Optional[FAISS]:
        """Load a FAISS index from disk with existence guard."""
        if not os.path.exists(path):
            logger.error(f'Vectorstore path does not exist: {path}')
            return None
        index_file = os.path.join(path, 'index.faiss')
        if not os.path.exists(index_file):
            logger.error(f'index.faiss not found in vectorstore directory: {path}')
            return None
        try:
            vs = FAISS.load_local(
                path, self.embeddings,
                allow_dangerous_deserialization=True,
            )
            logger.info(f'Vectorstore loaded: {path}')
            return vs
        except Exception as e:
            logger.exception(f'Failed to load vectorstore: {e}')
            return None

    def _get_doc_metadata(self, doc) -> dict:
        """Enrich doc metadata with fallbacks for video chunks if source_file is missing."""
        meta = doc.metadata or {}
        if not meta.get('source_file') and meta.get('video_title'):
            meta = meta.copy()
            meta['source_file'] = meta['video_title']
            meta['file_type'] = 'video_transcript'
            meta['chunk_role'] = 'single'
        return meta

    def query(
        self,
        vectorstore_path: str,
        question: str,
        course_title: str = 'Course',
        video_title: str = 'Video',
        k: int = None,
        filter_source_file: str = None,
        filter_file_type: str = None,
        file_manifest: list = None,  # List of {name, file_type, status} dicts from DB
    ) -> QueryResult:
        """Retrieve chunks via hybrid BM25+FAISS RRF and generate answer."""
        from django.conf import settings as django_settings
        start_time = time.time()

        if k is None:
            k = getattr(django_settings, 'VECTORSTORE_TOP_K', 6)

        # Detect SM-only mode (no video context)
        is_sm_mode = video_title == 'Study Material'

        # Detect overview/topic questions → broaden k to cover all files
        is_overview = any(p in question.lower() for p in OVERVIEW_PATTERNS)

        vectorstore = self.load(vectorstore_path)
        if vectorstore is None:
            return QueryResult(
                success=False,
                answer='Vectorstore not found.',
                error='missing_vectorstore',
            )

        # For overview queries, boost k to cover all unique files (capped at 20)
        if is_overview:
            try:
                unique_files = set()
                for doc in vectorstore.docstore._dict.values():
                    meta = self._get_doc_metadata(doc)
                    sf = meta.get('source_file', '')
                    if sf:
                        unique_files.add(sf)
                if unique_files:
                    k = max(k, min(len(unique_files) * 2, 20))
                    logger.info(f'[Overview] Boosted k to {k} for {len(unique_files)} unique files')
            except Exception:
                pass
        try:
            search_question = question

            # --- Query rewriting (Phase 3.3) ---
            if getattr(django_settings, 'QUERY_REWRITE_ENABLED', False):
                try:
                    rewrite_resp = self.llm.invoke(
                        'Rewrite the following search question to be more specific '
                        'and retrieve relevant technical content. Output only the '
                        f'rewritten question.\n\nQuestion: {question}'
                    )
                    search_question = rewrite_resp.content.strip()
                    logger.info(f'[QueryRewrite] "{question}" → "{search_question}"')
                except Exception as rw_err:
                    logger.warning(f'[QueryRewrite] failed, using original: {rw_err}')

            # --- Self-query metadata filter (Phase 3.4) ---
            auto_filter = {}
            if getattr(django_settings, 'SELF_QUERY_ROUTING_ENABLED', False):
                auto_filter = self._route_query(question)
                if auto_filter.get('file_type'):
                    filter_file_type = filter_file_type or auto_filter['file_type']
                if auto_filter.get('source_file'):
                    filter_source_file = filter_source_file or auto_filter['source_file']
            # --- Dense retrieval (over-fetch for RRF) ---
            over_k = k * 2
            dense_results = vectorstore.similarity_search_with_score(search_question, k=over_k)

            # Apply metadata filters
            if filter_source_file:
                dense_results = [
                    (doc, score) for doc, score in dense_results
                    if self._get_doc_metadata(doc).get('source_file') == filter_source_file
                ]
            if filter_file_type:
                dense_results = [
                    (doc, score) for doc, score in dense_results
                    if self._get_doc_metadata(doc).get('file_type') == filter_file_type
                ]

            # --- Dense per-file cap (prevents single large file from flooding) ---
            MAX_DENSE_PER_FILE = 2
            from collections import defaultdict as _dd2
            _dense_file_count = _dd2(int)
            capped_dense = []
            for doc, score in dense_results:
                sf = self._get_doc_metadata(doc).get('source_file', '__unknown__')
                if _dense_file_count[sf] < MAX_DENSE_PER_FILE:
                    capped_dense.append((doc, score))
                    _dense_file_count[sf] += 1
            dense_results = capped_dense

            # --- BM25 sparse retrieval ---
            bm25_path = os.path.join(vectorstore_path, 'bm25_index.pkl')
            bm25_results = []
            if os.path.exists(bm25_path):
                try:
                    with open(bm25_path, 'rb') as f:
                        bm25_data = pickle.load(f)
                    bm25 = bm25_data['bm25']

                    # Filter stopwords before scoring — common question words
                    # ("what", "can", "you", "tell", "me", "about" etc.) inflate
                    # prose PDFs 3× over code/binary files that lack casual prose.
                    _BM25_STOPWORDS = {
                        'a','an','the','is','are','was','were','be','been','being',
                        'have','has','had','do','does','did','will','would','could',
                        'should','may','might','shall','can','need','what','which',
                        'who','whom','this','that','these','those','i','me','my',
                        'we','our','you','your','he','him','his','she','her','it',
                        'its','they','them','their','and','or','but','if','while',
                        'although','because','since','as','at','by','for','in','of',
                        'on','to','up','with','about','into','through','tell','show',
                        'give','find','explain','describe','how','when','where','why',
                        'please','just','only','also','too','very','some','any','all',
                    }
                    raw_tokens = re.sub(r'[^\w\s]', ' ', question.lower()).split()
                    tokenized_query = [t for t in raw_tokens if t not in _BM25_STOPWORDS and t]
                    if not tokenized_query:  # guard: fallback if all words stripped
                        tokenized_query = raw_tokens

                    scores = bm25.get_scores(tokenized_query)
                    ranked_indices = sorted(
                        range(len(scores)), key=lambda i: scores[i], reverse=True
                    )

                    # Per-file cap: at most MAX_BM25_PER_FILE chunks from any one
                    # source file. Prevents a large multi-chunk PDF from occupying
                    # all over_k BM25 slots and excluding small (1-chunk) files
                    # that have the highest PER-FILE BM25 score.
                    MAX_BM25_PER_FILE = 2
                    from collections import defaultdict as _dd
                    _file_slot_count = _dd(int)
                    doc_ids = list(vectorstore.docstore._dict.keys())
                    for idx in ranked_indices:
                        if len(bm25_results) >= over_k:
                            break
                        if idx < len(doc_ids):
                            doc = vectorstore.docstore._dict[doc_ids[idx]]
                            meta = self._get_doc_metadata(doc)
                            sf = meta.get('source_file', '')
                            if _file_slot_count[sf] < MAX_BM25_PER_FILE:
                                bm25_results.append((doc, scores[idx]))
                                _file_slot_count[sf] += 1

                except Exception as bm25_err:
                    logger.warning(f'BM25 retrieval failed, dense-only: {bm25_err}')
            else:
                logger.warning(f'No bm25_index.pkl at {vectorstore_path}, dense-only')

            # --- RRF merge ---
            if bm25_results:
                final_docs = self._rrf_merge(dense_results, bm25_results, k)
            else:
                final_docs = [(doc, score) for doc, score in dense_results[:k]]

            # --- Guaranteed 1 chunk per file for overview queries (small files first) ---
            if is_overview:
                guaranteed = self._get_one_chunk_per_file(
                    vectorstore, max_files=OVERVIEW_MAX_GUARANTEED_FILES
                )
                # Build set of source_files already in final_docs
                covered = {self._get_doc_metadata(d).get('source_file', '') for d, _ in final_docs}
                # Prepend chunks from files NOT yet covered (small files first)
                injected = 0
                for gdoc in guaranteed:
                    meta = self._get_doc_metadata(gdoc)
                    gsf = meta.get('source_file', '')
                    if gsf and gsf not in covered:
                        final_docs.insert(0, (gdoc, 0.0))  # score 0.0 = guaranteed slot
                        covered.add(gsf)
                        injected += 1
                if injected:
                    logger.info(f'[Overview] Injected {injected} guaranteed file slots')

            if not final_docs:
                return QueryResult(success=False, error='No relevant chunks found')

            # --- Reorder context: BM25-boosted chunks lead (sorted by score), dense-only follow ---
            # RRF determines *which* docs to include; but the context order sent to
            # the LLM matters for attention ("lost in the middle" phenomenon). Sort
            # BM25-matched chunks by their raw BM25 score descending so the most
            # keyword-relevant chunks lead the context window.
            # A minimum score threshold filters noise matches (generic word overlap)
            # from the reorder set — they remain in final_docs via RRF but won't
            # be promoted to the front of the context.
            BM25_MIN_SCORE_THRESHOLD = 3.0  # empirical: SVG=19.55, code=6.85, noise=1.91
            meaningful_bm25 = (
                [(doc, score) for doc, score in bm25_results if score >= BM25_MIN_SCORE_THRESHOLD]
                if bm25_results else []
            )
            bm25_score_map = {id(doc): score for doc, score in meaningful_bm25}
            bm25_led = sorted(
                [(doc, s) for doc, s in final_docs if id(doc) in bm25_score_map],
                key=lambda x: bm25_score_map.get(id(x[0]), 0),
                reverse=True,
            )
            dense_only_docs = [(doc, s) for doc, s in final_docs if id(doc) not in bm25_score_map]
            context_ordered = bm25_led + dense_only_docs

            # --- Parent-child expansion + source collection ---
            context_docs = []
            retrieved_sources = []
            for doc, score in final_docs:  # keep retrieved_sources in RRF order for API
                meta = self._get_doc_metadata(doc)
                display_text = doc.page_content
                if meta.get('chunk_role') == 'child' and meta.get('parent_chunk_id'):
                    parent_text = self._find_parent(vectorstore, meta)
                    if parent_text:
                        display_text = parent_text

                context_docs.append(display_text)
                retrieved_sources.append({
                    'source_file': meta.get('source_file', ''),
                    'file_type': meta.get('file_type', ''),
                    'chunk_index': meta.get('chunk_index', 0),
                    'chunk_role': meta.get('chunk_role', ''),
                    'score': round(float(score), 4) if score else 0,
                    'header_context': meta.get('header_context'),
                    'page_number': meta.get('page_number'),
                    'function_name': meta.get('function_name'),
                })

            # Build annotated context (use BM25-led order for LLM)
            context_parts = []

            # Inject file manifest header if provided (overview queries)
            if file_manifest and is_overview:
                manifest_lines = []
                for f in file_manifest:
                    name = f.get('name', '')
                    ftype = f.get('file_type', '')
                    fstatus = f.get('status', '')
                    manifest_lines.append(f'  - {name} [{ftype}] (status: {fstatus})')
                total = len(file_manifest)
                shown = len(manifest_lines)
                manifest_text = (
                    f'[File Manifest] This study material contains {total} file(s):\n'
                    + '\n'.join(manifest_lines)
                )
                context_parts.append(manifest_text)
                logger.info(f'[Manifest] Injected {shown}/{total} files into context')

            # Build per-chunk text using context_ordered (BM25 results first)
            for doc, _score in context_ordered:
                meta = self._get_doc_metadata(doc)
                display_text = doc.page_content
                if meta.get('chunk_role') == 'child' and meta.get('parent_chunk_id'):
                    parent_text = self._find_parent(vectorstore, meta)
                    if parent_text:
                        display_text = parent_text
                source = meta.get('source_file', '')
                file_type = meta.get('file_type', '')
                ann = ''
                if source:
                    ann = f'[Source: {source}'
                    if file_type:
                        ann += f', Type: {file_type}'
                    ann += ']'
                context_parts.append(f'{ann}\n{display_text}' if ann else display_text)

            context = '\n\n'.join(context_parts)

            # Generate answer — select prompt based on mode
            if is_sm_mode:
                prompt_text = QA_PROMPT_SM.format(
                    context=context, question=question,
                    course_title=course_title,
                )
            else:
                prompt_text = QA_PROMPT_MIXED.format(
                    context=context, question=question,
                    course_title=course_title, video_title=video_title,
                )
            response = self.llm.invoke(prompt_text)
            answer = response.content

            latency_ms = int((time.time() - start_time) * 1000)
            top_score = retrieved_sources[0]['score'] if retrieved_sources else 0

            # Token usage logging (Phase 3.2)
            token_usage = {}
            try:
                rm = getattr(response, 'response_metadata', {})
                token_usage = rm.get('token_usage', {})
                if token_usage:
                    logger.info(
                        f'[TokenUsage] prompt={token_usage.get("prompt_tokens", "?")} '
                        f'completion={token_usage.get("completion_tokens", "?")} '
                        f'total={token_usage.get("total_tokens", "?")}'
                    )
            except Exception:
                pass

            # Score threshold warning (Phase 3.1 enhancement)
            score_threshold = getattr(django_settings, 'VECTORSTORE_SCORE_THRESHOLD', None)
            if score_threshold and top_score and top_score > score_threshold:
                logger.warning(
                    f'[Query] All scores below threshold ({score_threshold}). '
                    f'Top score: {top_score}. Results may be low quality.'
                )

            logger.info(
                f'[Query] path={vectorstore_path} top_k={k} '
                f'chunks={len(final_docs)} top_score={top_score} '
                f'latency={latency_ms}ms'
            )

            return QueryResult(
                success=True,
                answer=answer,
                source_chunks=len(final_docs),
                retrieved_sources=retrieved_sources,
                retrieved_chunk_count=len(final_docs),
            )

        except Exception as e:
            logger.exception(f'Query failed: {e}')
            return QueryResult(success=False, error=str(e))

    def _get_one_chunk_per_file(self, vectorstore, max_files: int = None) -> list:
        """
        Return one representative chunk per unique source_file.

        Prioritizes files with fewer chunks first (small/sparse files)
        so they are guaranteed a slot before large files consume the cap.
        If max_files is set, only the first max_files unique files are kept
        after sorting smallest-first.
        """
        # Count chunks per file
        file_chunks: dict[str, list] = {}
        for doc in vectorstore.docstore._dict.values():
            meta = self._get_doc_metadata(doc)
            sf = meta.get('source_file', '')
            if sf:
                file_chunks.setdefault(sf, []).append(doc)

        # Sort files by chunk count ascending → small/sparse files first
        sorted_files = sorted(file_chunks.items(), key=lambda x: len(x[1]))

        if max_files:
            sorted_files = sorted_files[:max_files]
            skipped = len(file_chunks) - len(sorted_files)
            if skipped > 0:
                logger.info(
                    f'[Overview] Guaranteed slots: {len(sorted_files)} files '
                    f'(capped at {max_files}, skipped {skipped} large files)'
                )

        # Pick the shortest chunk from each file (avoids token waste)
        result = []
        for _sf, docs in sorted_files:
            shortest = min(docs, key=lambda d: len(d.page_content))
            result.append(shortest)
        return result

    def _rrf_merge(self, dense_results, sparse_results, k: int):
        """Reciprocal Rank Fusion of dense + sparse results."""
        scores = {}
        doc_map = {}
        for rank, (doc, score) in enumerate(dense_results):
            doc_id = id(doc)
            scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (RRF_K + rank + 1)
            doc_map[doc_id] = (doc, score)
        for rank, (doc, score) in enumerate(sparse_results):
            doc_id = id(doc)
            scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (RRF_K + rank + 1)
            if doc_id not in doc_map:
                doc_map[doc_id] = (doc, score)
        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
        return [doc_map[did] for did in sorted_ids[:k]]

    def _find_parent(self, vectorstore, child_meta: dict) -> Optional[str]:
        """
        Find parent chunk text by matching source_file + page_number.

        parent_chunk_id format: "<source_file>:page_<page_number>"
        e.g. "NIST.CSWP.29 (1) - sweta dargad.pdf:page_22"

        We parse the target page number from parent_chunk_id and find the
        parent chunk with matching source_file AND page_number — NOT just the
        first parent by source_file (which would always return page 1).
        """
        try:
            parent_chunk_id = child_meta.get('parent_chunk_id')
            source_file = child_meta.get('source_file')
            if not parent_chunk_id or not source_file:
                return None
            # Parse target page from "filename:page_N" string
            try:
                target_page = int(parent_chunk_id.rsplit(':page_', 1)[1])
            except (ValueError, IndexError, AttributeError):
                target_page = None
            for doc in vectorstore.docstore._dict.values():
                m = self._get_doc_metadata(doc)
                if (m.get('chunk_role') == 'parent'
                        and m.get('source_file') == source_file
                        and target_page is not None
                        and m.get('page_number') == target_page):
                    return doc.page_content
        except Exception:
            pass
        return None

    def _route_query(self, question: str) -> dict:
        """Use LLM to extract metadata filters from the question (Phase 3.4)."""
        try:
            import json as json_mod
            resp = self.llm.invoke(
                'Given this search question, extract metadata filters if obvious. '
                'Return JSON with keys: file_type (one of: code, config, document, '
                'spreadsheet, image, presentation, or null), source_file (filename or null). '
                'Return only JSON, no explanation.\n\n'
                f'Question: {question}'
            )
            parsed = json_mod.loads(resp.content.strip())
            ft = parsed.get('file_type')
            sf = parsed.get('source_file')
            if ft or sf:
                logger.info(f'[SelfQueryRouter] file_type={ft}, source_file={sf}')
            return {'file_type': ft, 'source_file': sf}
        except Exception as e:
            logger.debug(f'[SelfQueryRouter] parse failed: {e}')
            return {}

    def test(self, path: str, test_query: str = 'What is this video about?') -> Dict[str, Any]:
        """Quick smoke-test for a vectorstore."""
        vs = self.load(path)
        if vs is None:
            return {'status': 'error', 'message': 'Failed to load vectorstore'}
        try:
            docs = vs.similarity_search(test_query, k=3)
            if not docs:
                return {'status': 'warning', 'message': 'Loaded but no documents found'}
            return {
                'status': 'ok',
                'document_count': len(docs),
                'avg_chunk_length': int(
                    sum(len(d.page_content) for d in docs) / len(docs)
                ),
                'sample': docs[0].page_content[:200],
            }
        except Exception as e:
            return {'status': 'error', 'message': str(e)}
