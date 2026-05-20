# Implementation Plan: Enhancing Small-File Retrieval Accuracy in Unified Vectorstore

## User Review Required

> [!IMPORTANT]
> **No Reprocessing of Vectorstore (Embeddings) is Required!**
> All fixes are query-time changes in `vectorstore.py`. No OpenAI calls needed.

---

## Confirmed Facts (from actual chunk JSON files)

### `parent_chunk_id` Schema (NOT an integer — a string)
Verified from `NIST.CSWP.29 (1) - sweta dargad_chunks.json`:
```
child chunk_index=68, page=22 → parent_chunk_id = "NIST.CSWP.29 (1) - sweta dargad.pdf:page_22"
child chunk_index=80, page=25 → parent_chunk_id = "NIST.CSWP.29 (1) - sweta dargad.pdf:page_25"
child chunk_index=2,  page=2  → parent_chunk_id = "NIST.CSWP.29 (1) - sweta dargad.pdf:page_2"
```
Format: `"<source_file>:page_<page_number>"`

### Correct Parent Exists (But Is Never Found)
The NIST PDF has **32 parent chunks**, one per page:
- `chunk_index=0` → page 1 (cover page: "The NIST Cybersecurity Framework (CSF) 2.0...")
- `chunk_index=67` → **page 22** (the CORRECT parent for child 68)

Current `_find_parent` iterates docstore and returns the **first** parent with matching `source_file` — which is always `chunk_index=0` (page 1 cover). The correct parent at `chunk_index=67` is never reached.

### JPEG Content — Confirmed Correct
Verified from `tempest - sweta dargad_chunks.json`:
```
chunk_role: "single", parent_chunk_id: null
text: "The image depicts a setup divided into two sections: a "Command room" on the
       left and an "Anechoic room" on the right... The anechoic room features an
       "Electromagnetic transducer"..."
```
The JPEG IS being retrieved (BM25 score 20.5532) and its content DOES describe an anechoic room. It does NOT trigger parent expansion (single role, null parent_chunk_id).

### Why the LLM Still Says "No Info" — Root Cause Traced
1. NIST child chunks 68 and 80 (pages 22, 25) trigger `_find_parent`.
2. `_find_parent` returns **page 1 cover text** (same short text, twice) for both.
3. The LLM context has: [page 1 cover × 2] + [JPEG: anechoic room] + [Module3 p134: Server Room Security] + [netflix_data.csv row] + [AI_Capabilities child].
4. "Server Room Security" (Module3) is a false-positive from dense retrieval (unrelated to TEMPEST).
5. The JPEG text describes anechoic room layout without explicitly using the word "TEMPEST" — but the file is annotated as `[Source: tempest - sweta dargad.jpeg]`. The LLM with strict "context-only" instruction may be uncertain.
6. After Bug 1 fix, NIST children expand to pages 22 & 25 (governance content — still not about TEMPEST), reducing noise. The JPEG then becomes the clearest/only relevant chunk for this query.

### Query Tokenization — Confirmed Issue (Secondary for this query)
Old code: `question.lower().split()` → `"tempest?"` (with `?`)
The JPEG still scored 20.5532 because `"anechoic"` and `"room"` tokens matched cleanly.
Bug mainly affects queries where the **final keyword itself** ends with `?` (e.g., `"pipeline?"`).

---

## Bugs to Fix

### Bug 1 — `_find_parent` Always Returns Wrong Parent ❌ NOT YET FIXED

**Code (lines 483–493, `vectorstore.py`):**
```python
def _find_parent(self, vectorstore, child_meta: dict) -> Optional[str]:
    """Find parent chunk text by matching source_file + chunk_role=parent."""
    try:
        for doc in vectorstore.docstore._dict.values():
            m = doc.metadata or {}
            if (m.get('chunk_role') == 'parent'
                    and m.get('source_file') == child_meta.get('source_file')):
                return doc.page_content   # ← ALWAYS returns page 1
    except Exception:
        pass
    return None
```

**Fix**: Parse the target page number from `parent_chunk_id` string (`"file.pdf:page_22"` → `22`), then match on `source_file` + `page_number`:

```python
def _find_parent(self, vectorstore, child_meta: dict) -> Optional[str]:
    """Find parent chunk by parsing page number from parent_chunk_id string."""
    try:
        parent_chunk_id = child_meta.get('parent_chunk_id')
        source_file = child_meta.get('source_file')
        if not parent_chunk_id or not source_file:
            return None
        # parent_chunk_id format: "filename.pdf:page_N"
        try:
            target_page = int(parent_chunk_id.rsplit(':page_', 1)[1])
        except (ValueError, IndexError):
            target_page = None
        for doc in vectorstore.docstore._dict.values():
            m = doc.metadata or {}
            if (m.get('chunk_role') == 'parent'
                    and m.get('source_file') == source_file
                    and target_page is not None
                    and m.get('page_number') == target_page):
                return doc.page_content
    except Exception:
        pass
    return None
```

### Bug 2 — Query Punctuation Tokenization ❌ NOT YET FIXED

**Code (line 243, `vectorstore.py`):**
```python
raw_tokens = question.lower().split()
```

**Fix**: Strip non-alphanumeric punctuation before splitting:
```python
import re
raw_tokens = re.sub(r'[^\w\s]', ' ', question.lower()).split()
```

---

## Proposed Changes

### [MODIFY] [vectorstore.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/services/vectorstore.py)

1. Add `import re` at top (if not already present).
2. Fix `_find_parent` (lines 483–493): match by parsed page number from `parent_chunk_id`.
3. Fix tokenizer (line 243): apply `re.sub(r'[^\w\s]', ' ', ...)` before `.split()`.

---

## Verification Plan

**Test query 1**: `"What is an anechoic room from tempest?"`
- After fix: NIST child 68 expands to page 22 content (not cover page), NIST child 80 expands to page 25 content.
- JPEG content remains in context and is the primary answer source.
- Expected: LLM describes anechoic room from the JPEG description.

**Test query 2**: `"What can you tell me about live video processing pipeline?"`
- After tokenization fix: token `"pipeline"` (not `"pipeline?"`) matches BM25 correctly.
- Expected: `live_video_pipeline_vulnerabilities.svg` and/or `process_live_videos.py` score higher.
