"""
Embedder service — text chunking + FAISS vectorstore creation.

Strategy: sequential mega-batches.
  Each batch is sized to consume nearly the full 60-second TPM budget
  (MAX_TOKENS_PER_BATCH ≈ 950k). This turns a 50k-chunk job from ~305
  small batches into ~32 large ones, minimising round-trips and the
  frequency of rate-limit sleeps.

  Batches are dispatched one at a time (no concurrency). Before each
  dispatch the OpenAIRateLimiter gates on both TPM and RPM; if budget
  is exhausted it sleeps with the lock released so nothing is blocked
  unnecessarily.

Tier 1 limits for text-embedding-3-small (enforced):
  - RPM : 3,000 requests/min  → safe limit 2,800
  - TPM : 1,000,000 tokens/min → safe limit 980,000

Auto-split safety net handles any 400 'maximum request size' errors.
Exponential backoff handles transient 429 / network errors.
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import aiohttp
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)

# ── Tuning constants ──────────────────────────────────────────────────────────
OPENAI_EMBED_URL      = "https://api.openai.com/v1/embeddings"
EMBED_MODEL           = "text-embedding-3-small"
MAX_BATCH_INPUTS      = 2048       # OpenAI hard cap on array length
MAX_TOKENS_PER_BATCH  = 280_000    # OpenAI per-request hard cap is 300k; stay safely under
BATCH_DELAY           = 0.5        # seconds between sequential batches
MAX_RETRIES           = 5          # 429 retry attempts
RETRY_BASE_DELAY      = 15         # seconds for first retry, doubles each attempt
TPM_LIMIT             = 980_000    # 98% of Tier 1 1M TPM — rolling-window budget
RPM_LIMIT             = 2_800      # 93% of Tier 1 3,000 RPM
# ─────────────────────────────────────────────────────────────────────────────


class OpenAIRateLimiter:
    """
    Dual rolling-window rate limiter — enforces both TPM and RPM.

    Each rolling window covers the last 60 seconds:
      - _token_log : List[(timestamp, token_count)] — for TPM
      - _req_log   : List[timestamp]                — for RPM

    Critical design: the asyncio.Lock is released BEFORE any sleep so
    waiting coroutines are NOT serialised. Each waiter independently
    checks budget after waking, grabs the lock, and either records its
    entry or sleeps again — no convoy effect.
    """

    def __init__(self, tpm_limit: int = TPM_LIMIT, rpm_limit: int = RPM_LIMIT):
        self.tpm_limit = tpm_limit
        self.rpm_limit = rpm_limit
        self._token_log: List[Tuple[float, int]] = []  # (timestamp, tokens)
        self._req_log:   List[float] = []              # timestamp per request
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int) -> None:
        """
        Block until both TPM and RPM budgets permit dispatching `tokens`.
        The lock is released before every sleep so waiters run concurrently.
        """
        while True:
            sleep_for = 0.0
            reason_parts: List[str] = []

            async with self._lock:
                now = time.monotonic()
                cutoff = now - 60.0

                # Purge expired entries from both windows
                self._token_log = [(ts, t) for ts, t in self._token_log if ts > cutoff]
                self._req_log   = [ts for ts in self._req_log if ts > cutoff]

                consumed_tokens = sum(t for _, t in self._token_log)
                consumed_reqs   = len(self._req_log)

                tpm_ok = consumed_tokens + tokens <= self.tpm_limit
                rpm_ok = consumed_reqs + 1        <= self.rpm_limit

                if tpm_ok and rpm_ok:
                    # Budget available — record and return immediately
                    self._token_log.append((now, tokens))
                    self._req_log.append(now)
                    return

                # Compute minimum sleep needed to free up the binding window
                if not tpm_ok and self._token_log:
                    oldest_ts = self._token_log[0][0]
                    sleep_for = max(sleep_for, 60.0 - (now - oldest_ts))
                    reason_parts.append(f'TPM {consumed_tokens:,}/{self.tpm_limit:,}')

                if not rpm_ok and self._req_log:
                    oldest_req = self._req_log[0]
                    sleep_for = max(sleep_for, 60.0 - (now - oldest_req))
                    reason_parts.append(f'RPM {consumed_reqs}/{self.rpm_limit}')

                sleep_for = max(sleep_for, 0.05)  # minimum 50 ms guard

            # ← Lock is RELEASED here before sleeping.
            # All other waiters can now check/acquire budget concurrently.
            logger.debug(
                f'[RateLimiter] Throttled ({", ".join(reason_parts)}), '
                f'sleeping {sleep_for:.1f}s'
            )
            await asyncio.sleep(sleep_for)

@dataclass
class EmbedResult:
    success: bool
    vectorstore_path: str = ''
    chunk_count: int = 0
    error: str = ''


class Embedder:
    """
    Chunk transcript text and create a FAISS vectorstore using OpenAI embeddings.

    Embedding is done via direct async HTTP batching (aiohttp) rather than
    the sequential langchain path, reducing API call count by ~100x for large
    documents.
    """

    def __init__(
        self,
        openai_api_key: str,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ):
        self.api_key = openai_api_key
        # Keep an OpenAIEmbeddings instance only for FAISS index operations
        # (merge / load_local) — actual embedding calls bypass this.
        self.embeddings = OpenAIEmbeddings(
            openai_api_key=openai_api_key,
            model=EMBED_MODEL,
        )
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=['\n\n', '\n', '. ', ' ', ''],
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Public API (signature unchanged)
    # ─────────────────────────────────────────────────────────────────────────

    def create_vectorstore(
        self,
        transcript_text: str,
        save_path: str,
        metadata: Optional[dict] = None,
    ) -> EmbedResult:
        """
        Chunk the transcript, embed with OpenAI (batched async), and save as
        a FAISS index.

        Args:
            transcript_text: Full transcript text.
            save_path:        Absolute directory path to save the FAISS index.
            metadata:         Optional metadata to attach to every chunk.

        Returns:
            EmbedResult with the saved path and chunk count.
        """
        if not transcript_text or not transcript_text.strip():
            return EmbedResult(success=False, error='Empty transcript text')

        try:
            # 1. Chunk
            chunks = self.text_splitter.split_text(transcript_text)
            if not chunks:
                return EmbedResult(success=False, error='Text splitter produced no chunks')

            logger.info(f'Split transcript into {len(chunks)} chunks')

            # 2. Embed — async batched path
            vectors = asyncio.run(self._embed_all(chunks))

            if len(vectors) != len(chunks):
                return EmbedResult(
                    success=False,
                    error=f'Embedding mismatch: got {len(vectors)} vectors for {len(chunks)} chunks',
                )

            # 3. Build metadatas list
            metadatas: Optional[List[dict]] = None
            if metadata:
                metadatas = [metadata.copy() for _ in chunks]

            # 4. Build FAISS index from pre-computed embeddings
            text_embedding_pairs: List[Tuple[str, List[float]]] = list(zip(chunks, vectors))
            vectorstore = FAISS.from_embeddings(
                text_embeddings=text_embedding_pairs,
                embedding=self.embeddings,
                metadatas=metadatas,
            )

            # 5. Save to disk
            os.makedirs(save_path, exist_ok=True)
            vectorstore.save_local(save_path)
            logger.info(f'Vectorstore saved: {save_path} ({len(chunks)} chunks)')

            return EmbedResult(
                success=True,
                vectorstore_path=save_path,
                chunk_count=len(chunks),
            )

        except Exception as e:
            logger.exception(f'Vectorstore creation failed: {e}')
            return EmbedResult(success=False, error=str(e))

    def embed_chunks(
        self,
        chunks,
        save_path: str,
    ) -> 'EmbedResult':
        """
        Embed pre-split EnrichedChunk objects with per-chunk metadata.

        Unlike create_vectorstore(), this method skips the internal
        RecursiveCharacterTextSplitter — chunks are already split by
        ModalityRouter handlers. Each chunk carries its own metadata dict.

        Args:
            chunks: List of EnrichedChunk (text + metadata dict).
            save_path: Absolute directory path to save the FAISS index.

        Returns:
            EmbedResult with the saved path and chunk count.
        """
        if not chunks:
            return EmbedResult(success=False, error='No chunks provided')

        try:
            texts = [c.text for c in chunks]
            metadatas = [c.metadata.copy() for c in chunks]

            logger.info(f'Embedding {len(texts)} pre-split chunks')

            # Embed — async batched path (same as create_vectorstore)
            vectors = asyncio.run(self._embed_all(texts))

            if len(vectors) != len(texts):
                return EmbedResult(
                    success=False,
                    error=f'Embedding mismatch: {len(vectors)} vectors for {len(texts)} chunks',
                )

            # Build FAISS index from pre-computed embeddings + per-chunk metadata
            text_embedding_pairs: List[Tuple[str, List[float]]] = list(zip(texts, vectors))
            vectorstore = FAISS.from_embeddings(
                text_embeddings=text_embedding_pairs,
                embedding=self.embeddings,
                metadatas=metadatas,
            )

            os.makedirs(save_path, exist_ok=True)
            vectorstore.save_local(save_path)

            # Build BM25 sparse index alongside FAISS for hybrid search
            try:
                import pickle, re as _re
                from rank_bm25 import BM25Okapi

                def _stem_tokens(source_file: str) -> list:
                    """Split a filename stem into searchable word tokens.

                    'process_live_videos.py' → ['process', 'live', 'videos']
                    'live_video_pipeline_vulnerabilities.svg' →
                        ['live', 'video', 'pipeline', 'vulnerabilities']
                    These are prepended to each chunk's token list so keyword
                    queries about the file's topic always match it strongly.
                    """
                    stem = _re.sub(r'\.[^.]+$', '', source_file)  # strip extension
                    parts = _re.split(r'[\s_\-.]+', stem.lower())
                    tokens = []
                    for p in parts:
                        # CamelCase split: 'processLiveVideo' → ['process','live','video']
                        tokens += [w.lower() for w in _re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)', p) or [p]]
                    return [t for t in tokens if len(t) > 2]

                # Prepend filename tokens to each chunk's BM25 corpus entry so
                # queries containing filename keywords always retrieve that file.
                tokenized = [
                    _stem_tokens(m.get('source_file', '')) + t.lower().split()
                    for m, t in zip(metadatas, texts)
                ]
                # b=0.5: lower length normalization penalty for 1-chunk small files
                bm25 = BM25Okapi(tokenized, b=0.5)
                bm25_path = os.path.join(save_path, 'bm25_index.pkl')
                with open(bm25_path, 'wb') as f:
                    pickle.dump({'bm25': bm25, 'corpus': tokenized, 'metadatas': metadatas}, f)
                logger.info(f'BM25 index saved: {bm25_path}')
            except Exception as bm25_err:
                logger.warning(f'BM25 index build failed (non-fatal): {bm25_err}')

            logger.info(f'Vectorstore saved: {save_path} ({len(texts)} chunks with metadata)')

            return EmbedResult(
                success=True,
                vectorstore_path=save_path,
                chunk_count=len(texts),
            )

        except Exception as e:
            logger.exception(f'embed_chunks failed: {e}')
            return EmbedResult(success=False, error=str(e))

    # ─────────────────────────────────────────────────────────────────────────
    # Async batched embedding internals
    # ─────────────────────────────────────────────────────────────────────────

    async def _embed_all(self, chunks: List[str]) -> List[List[float]]:
        """
        Embed all chunks sequentially, one mega-batch at a time.

        Each batch is sized to consume nearly the full 60-second TPM budget
        (MAX_TOKENS_PER_BATCH = 950k), so a 50k-chunk job produces ~32
        batches instead of ~305. OpenAIRateLimiter gates each dispatch on
        both TPM and RPM; the lock is released during any sleep so nothing
        is blocked unnecessarily.
        """
        batches = self._plan_batches(chunks)
        total_batches = len(batches)

        logger.info(
            f'[Embedder] Planned {total_batches} sequential batches for {len(chunks):,} chunks '
            f'(TPM limit {TPM_LIMIT:,}, RPM limit {RPM_LIMIT:,})'
        )

        # Pre-compute exact token counts for every chunk up front
        import tiktoken
        try:
            enc = tiktoken.encoding_for_model(EMBED_MODEL)
        except Exception:
            enc = tiktoken.get_encoding('cl100k_base')
        token_counts = [len(t) for t in enc.encode_batch(chunks, disallowed_special=())]

        rate_limiter = OpenAIRateLimiter(tpm_limit=TPM_LIMIT, rpm_limit=RPM_LIMIT)
        all_vectors: List[List[float]] = []

        async with aiohttp.ClientSession() as session:
            for idx, (b_start, b_end) in enumerate(batches):
                batch_texts  = chunks[b_start:b_end]
                batch_tokens = sum(token_counts[b_start:b_end])

                # Block until TPM + RPM budget allows this batch
                await rate_limiter.acquire(batch_tokens)

                vectors = await self._embed_batch(
                    session, batch_texts, idx + 1, total_batches
                )
                all_vectors.extend(vectors)
                await asyncio.sleep(BATCH_DELAY)

        return all_vectors

    def _plan_batches(self, chunks: List[str]) -> List[Tuple[int, int]]:
        """
        Plan batch boundaries so each batch stays under both
        MAX_BATCH_INPUTS and MAX_TOKENS_PER_BATCH using exact
        token counting via tiktoken.

        Returns a list of (start_index, end_index) tuples.
        """
        import tiktoken
        try:
            enc = tiktoken.encoding_for_model(EMBED_MODEL)
        except Exception:
            enc = tiktoken.get_encoding("cl100k_base")

        # Exact token counts — Rust-parallel, <100ms for 50k chunks
        token_counts = [
            len(tokens)
            for tokens in enc.encode_batch(chunks, disallowed_special=())
        ]

        batches: List[Tuple[int, int]] = []
        i = 0
        n = len(chunks)
        while i < n:
            batch_tokens = 0
            batch_count = 0
            j = i
            while j < n and batch_count < MAX_BATCH_INPUTS:
                if batch_tokens + token_counts[j] > MAX_TOKENS_PER_BATCH and batch_count > 0:
                    break
                batch_tokens += token_counts[j]
                batch_count += 1
                j += 1
            batches.append((i, j))
            i = j
        return batches

    async def _embed_batch(
        self,
        session: aiohttp.ClientSession,
        texts: List[str],
        batch_num: int,
        total_batches: int,
    ) -> List[List[float]]:
        """
        Embed one batch of texts with retry logic for 429 rate-limit errors.
        """
        payload = {"input": texts, "model": EMBED_MODEL}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with session.post(
                    OPENAI_EMBED_URL,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        vectors = [item["embedding"] for item in data["data"]]
                        logger.info(
                            f'[Embedder] Batch {batch_num}/{total_batches} '
                            f'→ {len(vectors)} embeddings'
                        )
                        return vectors

                    elif resp.status == 429:
                        delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                        logger.warning(
                            f'[Embedder] 429 rate limit on batch {batch_num} '
                            f'(attempt {attempt}/{MAX_RETRIES}), retrying in {delay}s…'
                        )
                        await asyncio.sleep(delay)

                    elif resp.status == 400:
                        body = await resp.text()
                        # Catch both error strings OpenAI uses for oversized requests:
                        #   'maximum request size'  — older models
                        #   'max_tokens_per_request' — embeddings endpoint
                        is_too_large = (
                            'maximum request size' in body
                            or 'max_tokens_per_request' in body
                        )
                        if is_too_large and len(texts) > 1:
                            # Safety net: split batch in half and retry both halves
                            mid = len(texts) // 2
                            logger.warning(
                                f'[Embedder] Batch {batch_num} too large '
                                f'({len(texts)} inputs), splitting in half and retrying'
                            )
                            left = await self._embed_batch(
                                session, texts[:mid], batch_num, total_batches,
                            )
                            await asyncio.sleep(BATCH_DELAY)
                            right = await self._embed_batch(
                                session, texts[mid:], batch_num, total_batches,
                            )
                            return left + right
                        raise RuntimeError(
                            f'OpenAI embeddings API error {resp.status}: {body}'
                        )

                    else:
                        body = await resp.text()
                        raise RuntimeError(
                            f'OpenAI embeddings API error {resp.status}: {body}'
                        )

            except aiohttp.ClientError as exc:
                if attempt == MAX_RETRIES:
                    raise
                delay = RETRY_BASE_DELAY * attempt
                logger.warning(
                    f'[Embedder] Network error on batch {batch_num}: {exc}. '
                    f'Retrying in {delay}s…'
                )
                await asyncio.sleep(delay)

        raise RuntimeError(
            f'Batch {batch_num} failed after {MAX_RETRIES} attempts (persistent 429)'
        )
