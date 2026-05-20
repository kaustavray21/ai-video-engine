# Walkthrough: Study Material Merge-to-Course Pipeline updates

## Overview
We identified and resolved an issue in the Study Material merging pipeline. Previously, merging a Study Material into a Course only combined the FAISS indexes and docstores, but omitted rebuilding the unified BM25 index. This caused hybrid RAG queries on merged courses to fall back to dense-only search.

## Changes Made

### 1. Rebuild BM25 on Course Merge
- **[MODIFY] `study_material_merger.py`**:
  - Imported `StudyMaterialProcessor` and called `_rebuild_bm25` on the newly merged FAISS index inside the `build` method.
  - This ensures that a unified `bm25_index.pkl` is built and saved alongside the FAISS index files in the course's `merged_vectorstore_path`.

### 2. Video Title Fallback for BM25 Tokenization
- **[MODIFY] `study_material_processor.py`**:
  - Updated the static `_rebuild_bm25` method to use a fallback key when extracting token stems.
  - If a chunk lacks `source_file` but contains `video_title` (the default structure for video transcript chunks), it falls back to tokenizing the `video_title`.
  - This makes video content indexable and searchable by its titles in the combined BM25 index.
