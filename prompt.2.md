# Batch Processing Speed Audit & Optimization Prompt

# For Claude Opus — paste into your system/session

---

## Context

You have access to this project's knowledge base already located at:
`project_local_knowledge_base/`

Read `kb_map.toon.json`, `kb_deps.toon.json`, and `kb_updates.toon.json` first
before doing anything else. Do not assume — verify everything from the actual files.

---

## Your Task

I need you to audit and improve the speed of our embedding batch processing pipeline.
The logs show batches like `Batch 167/7 13 → 400 embeddings` running sequentially,
which is very slow. I want you to:

1. Understand what is currently implemented
2. Identify what speed optimizations are already in place vs missing
3. Create a concrete, prioritized fix plan
4. Stage the changes for my approval before writing anything

---

## Phase 1 — Audit the Current Implementation

Read these files carefully (use the KB map to find exact paths if needed):

- `apps/core/services/embedder.py` — core embedding logic, batch size, API calls
- `apps/core/services/study_material_processor.py` — phase1/phase2 orchestration
- `apps/core/tasks/study_material_tasks.py` — Celery task definitions
- `apps/core/services/study_material_merger.py` — merger logic
- `apps/core/models/study_material.py` — status fields
- `apps/core/models/study_material_file.py` — file status fields
- `config/settings.py` — look for CELERY*, OPENAI*, BATCH\_ config vars

After reading, report your findings in this exact format:

```
CURRENT STATE AUDIT
===================
Batch size:             [value + file:line where found]
Sequential or parallel: [sequential loop / ThreadPool / asyncio — file:line]
Async OpenAI client:    [yes/no — file:line]
Celery concurrency:     [value or "not set" — file:line]
Skip already-embedded:  [yes/no — describe logic if yes]
Retry on rate limit:    [yes/no — describe logic if yes]
Embedding model:        [model name — file:line]
Any other optimizations already present: [list them]
```

Also check `kb_updates.toon.json` — list any past changes related to
embeddings, batch processing, or performance so we don't redo work.

---

## Phase 2 — Gap Analysis

Based on your audit, produce a gap table covering these optimizations.
Mark each as DONE / MISSING / PARTIAL and give a realistic speedup estimate
based on what you actually found in the code (not generic estimates):

| #   | Optimization                                       | Status | Est. Speedup | Effort | Notes                    |
| --- | -------------------------------------------------- | ------ | ------------ | ------ | ------------------------ |
| 1   | Increase batch size to 500–1000                    | ?      | ?            | LOW    | OpenAI allows up to 2048 |
| 2   | Parallel batch requests (ThreadPoolExecutor)       | ?      | ?            | MED    |                          |
| 3   | Skip already-embedded files by status check        | ?      | ?            | LOW    |                          |
| 4   | Celery worker concurrency increase                 | ?      | ?            | LOW    |                          |
| 5   | Async OpenAI client (AsyncOpenAI + asyncio.gather) | ?      | ?            | MED    |                          |
| 6   | Exponential backoff retry on 429 RateLimitError    | ?      | ?            | LOW    |                          |
| 7   | Per-file Celery task fan-out                       | ?      | ?            | HIGH   |                          |

Only include items that are actually MISSING or PARTIAL — skip what is already done.

---

## Phase 3 — Prioritized Fix Plan

For each MISSING or PARTIAL item, provide:

**Fix N — [Name]**

- File to change: `path/to/file.py`
- Exact lines affected: [line range]
- What the current code does (quote the relevant lines)
- What the new code should do (write the exact replacement code)
- Why this helps (one sentence)
- Any risk or side effect to watch for

Order fixes by: highest speedup × lowest effort first.

At the end, give a realistic before/after estimate:

```
EXPECTED SPEEDUP
================
Before: [X batches × Y items, sequential] ≈ [time estimate based on log timestamps]
After:  [X batches × Y items, parallel]   ≈ [time estimate]
Overall improvement: ~Nx
```

Base the time estimates on the actual log timestamps visible in the terminal
(e.g. 2026-05-18 05:33:52 → 05:35:08 per batch), not generic numbers.

---

## Phase 4 — Stage Changes for Approval

Do NOT write to any source file yet.

Instead:

1. Write all proposed changes to `project_local_knowledge_base/pending_changes.json`
2. Show me a clear diff for each file (before / after)
3. List which files will be touched and how many lines change
4. Ask me: "Shall I apply these changes? Reply 'apply all', 'apply fix N', or 'skip fix N'."

Only write to source files after I confirm.

---

## Phase 5 — After I Approve

Once I say apply:

1. Write the changes to the source files
2. Show the final diff for each file written
3. Update `kb_updates.toon.json` with an entry for each change
4. Tell me exactly how to verify it worked:
   - What to look for in the logs
   - What the new batch log lines should look like
   - Any config values I may need to set (env vars, worker startup flags)

---

## Constraints

- Read the knowledge base first — do not re-scan files already mapped
- Do not guess at line numbers — find them from the actual file content
- Do not apply any change without my explicit approval
- If you find something unexpected (e.g. a custom embedder wrapper, a queue system,
  rate limit middleware already in place), stop and tell me before continuing
- Prefer the lowest-risk fix first — we want the server to keep running

---

Begin now. Start with Phase 1.
