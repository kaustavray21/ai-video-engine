# RAG Pipeline Upgrade — All Phases Complete

## What Was Done

### Phase 1 — Modality-Aware Ingestion
- **NEW** `apps/core/services/modality_router.py` — ModalityRouter + 4 handlers (Document/Image/Structured/Code)
- **MOD** `embedder.py` — `embed_chunks()` method for pre-split EnrichedChunks
- **MOD** `study_material_processor.py` — Wired ModalityRouter into pipeline
- **MOD** `file_converter.py` — Post-OCR cleanup
- **MOD** `vectorstore.py` — Grounded QA_PROMPT + empty-VS guard
- **MOD** `config/settings.py` — RAG settings (TOP_K, IMAGE_VLM_ENABLED, etc.)

### Phase 2 — Retrieval Quality
- **MOD** `embedder.py` — BM25 index built alongside FAISS
- **MOD** `vectorstore.py` — Hybrid BM25+FAISS via RRF, parent-child expansion
- **MOD** `query_views.py` — `retrieved_sources` + `filter_source_file` in API
- **MOD** `study_material_views.py` — Refactored to use `VectorStoreManager.query()`
- **MOD** `requirements.txt` — Added `rank-bm25`

### Phase 3 — Observability & Routing
- **MOD** `vectorstore.py` — Token usage logging, query rewrite, self-query router, score threshold warning
- **MOD** `StudyMaterialsView.tsx` — Collapsible retrieved_sources panel + error tooltip
- **MOD** `api.ts` — Updated return types for `queryStudyMaterial`
- **MOD** `types/index.ts` — Added `error_log` to StudyMaterial interface
- **NEW** `notes/rag_eval/test_questions.json` — 15 baseline test questions
- **NEW** `notes/rag_eval/eval_runner.py` — Automated RAG regression runner
- **NEW** `notes/rag_eval/regression_cases.json` — Edge case documentation

---

## Commands To Run Now

### 1. Install new dependency
```bash
pip install rank-bm25==0.2.2 --break-system-packages
```

### 2. Restart Celery (picks up new code)
```bash
celery -A config worker -l info --concurrency=4
```

### 3. Rebuild dashboard (picks up TSX changes)
```bash
cd dashboard && npm run build && cd ..
```

### 4. Test with a ZIP upload
```bash
curl -X POST http://localhost:8000/api/study-materials/upload/ \
  -F "name=test_rag_full" \
  -F "zip_file=@/path/to/test.zip"
```

### 5. Verify FAISS metadata (Django shell)
```python
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from django.conf import settings
vs = FAISS.load_local('<vs_path>', OpenAIEmbeddings(openai_api_key=settings.OPENAI_API_KEY), allow_dangerous_deserialization=True)
doc = list(vs.docstore._dict.values())[0]
print(doc.metadata)  # Should have source_file, file_type, chunk_role, etc.
```

### 6. Verify BM25 index exists
```bash
ls media/study_materials_vectorstore/individual_vectorstores/*/bm25_index.pkl
```

### 7. Test grounded refusal
```bash
curl -X POST http://localhost:8000/api/study-materials/<id>/query/ \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the capital of Mars?"}'
# Expected: "The provided context does not contain information about this topic."
```

### 8. Test filter_source_file
```bash
curl -X POST http://localhost:8000/api/study-materials/<id>/query/ \
  -H "Content-Type: application/json" \
  -d '{"question": "summarize", "filter_source_file": "specific_file.pdf"}'
```

### 9. Run RAG eval (after processing a SM)
```bash
python notes/rag_eval/eval_runner.py
```

### 10. Enable optional features via .env
```env
QUERY_REWRITE_ENABLED=True       # LLM rewrites vague queries
SELF_QUERY_ROUTING_ENABLED=True  # LLM auto-filters by file_type
IMAGE_VLM_ENABLED=False          # Set False to skip GPT-4o vision costs
```
