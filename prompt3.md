# Project RAG System Planning Prompt

Use this prompt to create a concrete improvement plan for the `ai_video_engine`
RAG system using the local knowledge base.

---

## Context

You are working inside the `ai_video_engine` Django project.

The project already has a local knowledge base in TOON markdown format:

`project_local_knowledge_base/project_local_knowledge_base_toon.md`

Before creating any plan, read that markdown file fully. It contains TOON-converted
project knowledge from:

- `kb_map.toon.json` — project file map, purpose, imports, exports, tags, structure
- `kb_deps.toon.json` — dependency/call relationships between APIs, services, tasks, and UI
- `kb_updates.toon.json` — implementation history and recent changes

Do not guess from generic RAG advice. Use the project knowledge base as the
source of truth, then verify important details from the actual source files.

---

## Project Requirements

Create a practical plan to improve the existing RAG system for videos, courses,
and study materials.

The current system includes:

- Django REST API endpoints for courses, videos, queries, dashboard logs, and study materials
- Celery tasks for video processing, course vectorstore rebuilds, and study material processing
- FAISS vectorstores for video, course, individual study material files, complete study materials, and merged course + study material retrieval
- OpenAI embeddings through `apps/core/services/embedder.py`
- RAG query handling through `apps/core/services/vectorstore.py`
- Study material upload, conversion, per-file tracking, retry, query, and merge-to-course flows
- React dashboard UI with API testing and study material management

The plan must account for everything already mentioned in the TOON markdown file,
especially:

- Existing async batched embedding work
- Token bucket rate limiting
- Per-file study material checkpointing
- Retry behavior for failed study material processing
- Course query support for `include_study_materials`
- Merged vectorstore behavior
- Celery time limit and task registration details
- File conversion/OCR dependencies
- Logging rotation and verification workflow

---

## Goal

Produce a step-by-step implementation plan for improving RAG quality,
retrieval accuracy, observability, and reliability without breaking the current
study material pipeline.

The plan should focus on project-specific changes, not a generic RAG checklist.

---

## Required Audit

Read the TOON markdown knowledge base first, then inspect the actual files needed
to verify details. At minimum, audit:

- `apps/core/services/vectorstore.py`
- `apps/core/services/embedder.py`
- `apps/core/services/study_material_processor.py`
- `apps/core/services/study_material_merger.py`
- `apps/core/services/file_converter.py`
- `apps/core/tasks/processing.py`
- `apps/core/tasks/study_material_tasks.py`
- `apps/core/api/views/query_views.py`
- `apps/core/api/views/study_material_views.py`
- `apps/core/models/course.py`
- `apps/core/models/study_material.py`
- `apps/core/models/study_material_file.py`
- `dashboard/src/components/StudyMaterialsView.tsx`
- `dashboard/src/services/api.ts`
- `config/settings.py`
- `config/celery.py`

Also use `kb_updates.toon.json` history from the markdown file to avoid planning
work that has already been implemented.

---

## Plan Areas

Create a plan that covers these areas:

1. **Current Architecture**
   - Explain the current video, course, study material, and merged-vectorstore RAG flows.
   - Identify which files own ingestion, chunking, embedding, storage, retrieval, and answer generation.

2. **Data Quality and Chunking**
   - Evaluate current text conversion and chunking behavior.
   - Plan improvements such as semantic chunking, metadata-enriched chunks, source labels, page/slide/sheet tracking, and chunk overlap tuning.
   - Preserve existing per-file checkpointing and retry behavior.

3. **Retrieval Quality**
   - Evaluate current similarity search behavior.
   - Plan project-compatible retrieval improvements such as metadata filtering, hybrid search, query rewriting, multi-query retrieval, top-k tuning, context compression, and reranking.
   - Specify whether each improvement should apply to video queries, study material queries, course queries, or merged course + study material queries.

4. **Grounded Answer Generation**
   - Review the current QA prompt and answer behavior.
   - Plan prompt changes so the model answers only from retrieved context, cites sources, admits missing information, and separates video transcript evidence from study material evidence when both are used.

5. **Evaluation and Testing**
   - Define a lightweight RAG evaluation workflow for this project.
   - Include test questions, expected source coverage, faithfulness checks, answer relevance checks, and regression cases for merged vectorstores.
   - Include how to test retries, failed files, empty vectorstores, and missing study material attachments.

6. **Observability**
   - Plan logging and dashboard/API response improvements.
   - Include retrieved source count, vectorstore path used, similarity scores if available, model name, latency, token counts if practical, and error reasons.

7. **Performance and Reliability**
   - Respect existing async batching, rate limiting, and Celery behavior.
   - Plan only improvements that fit the current architecture unless a larger refactor is clearly justified.
   - Identify risks around OpenAI rate limits, FAISS loading, Celery timeouts, large ZIP uploads, OCR, and merged vectorstore rebuilds.

8. **Frontend/API Experience**
   - Plan user-facing improvements in the dashboard only where useful.
   - Include source display, query mode selection, include/exclude study materials, retry visibility, file-level status, and merge status.

---

## Output Format

Return the plan in this exact structure:

```md
# RAG Improvement Plan

## 1. Current State From Knowledge Base

- [Summarize what the TOON markdown says about the current system]
- [Mention specific files and responsibilities]
- [Mention recent updates that must not be duplicated]

## 2. Verified Architecture

| Flow | Entry Point | Main Files | Vectorstore Used | Notes |
| --- | --- | --- | --- | --- |
| Video query | ... | ... | ... | ... |
| Course query | ... | ... | ... | ... |
| Study material query | ... | ... | ... | ... |
| Course + study material query | ... | ... | ... | ... |

## 3. Gaps And Risks

| Area | Current Behavior | Gap/Risk | Evidence | Priority |
| --- | --- | --- | --- | --- |

## 4. Recommended Implementation Phases

### Phase 1 — Low-Risk Accuracy Wins

- Change:
- Files:
- Reason:
- Risk:
- Verification:

### Phase 2 — Retrieval Improvements

- Change:
- Files:
- Reason:
- Risk:
- Verification:

### Phase 3 — Evaluation And Observability

- Change:
- Files:
- Reason:
- Risk:
- Verification:

### Phase 4 — Optional Larger Refactors

- Change:
- Files:
- Reason:
- Risk:
- Verification:

## 5. Exact File-Level Plan

| # | File | Change | Why | Risk | Test/Verification |
| --- | --- | --- | --- | --- | --- |

## 6. API And UI Changes

| Endpoint/UI | Proposed Change | Backward Compatible? | Notes |
| --- | --- | --- | --- |

## 7. Testing Checklist

- [ ] Upload ZIP with multiple files and verify per-file processing
- [ ] Retry failed study material processing
- [ ] Query a study material directly
- [ ] Query a course without study materials
- [ ] Query a course with `include_study_materials=true`
- [ ] Query a course with `include_study_materials=false`
- [ ] Verify source citations and vectorstore path used
- [ ] Verify answer refuses unsupported claims
- [ ] Verify logs include useful retrieval diagnostics

## 8. Approval Gate

Do not edit source files yet.

List the proposed files to change and ask:
"Shall I apply this plan? Reply `apply phase 1`, `apply phase N`, or `revise plan`."
```

---

## Constraints

- Do not write source code during planning.
- Do not overwrite existing user changes.
- Do not remove existing study material retry, checkpointing, async embedding, or merged vectorstore behavior.
- Do not propose replacing FAISS unless the plan clearly explains migration cost and compatibility risk.
- Prefer incremental changes that can be verified through existing APIs and logs.
- Every recommendation must cite either the TOON markdown knowledge base or an actual source file.
- If the knowledge base and source code disagree, trust the source code and mention the mismatch.

Begin by reading:

`project_local_knowledge_base/project_local_knowledge_base_toon.md`
