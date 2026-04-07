# AI Video Engine Dashboard — V2 Redesign Updates

**Date:** March 30, 2026
**Summary:** Complete refactoring and redesign of the React dashboard frontend and associated Django backend APIs to support advanced API testing, history tracking, and analytics.

## Backend Changes

1.  **New API Call Logging Model:**
    *   Created `ApiCallLog` model to persist dashboard API requests.
    *   Tracks `method`, `endpoint`, `request_body`, `response_body`, `status_code`, `latency_ms`, and explicitly explicitly `saved` logs for history.
    *   Registered in Django admin.

2.  **API Endpoint Restructuring (URL parameters moved to body):**
    *   Refactored all endpoints that previously relied on URL parameters (e.g., `GET /api/courses/{id}/`) to be entirely `POST` requests, receiving the necessary IDs (like `course_id` or `video_id`) in the JSON payload body.
    *   Simplified URL routing by eliminating all parameterized URL paths.

3.  **New Dashboard Analytics & Logging Endpoints:**
    *   `POST /api/dashboard/log/`: Automatically called by the frontend to log every request.
    *   `POST /api/dashboard/logs/`: Fetch logs with optional filtering by date and `saved_only=True`.
    *   `POST /api/dashboard/logs/save/`: Marks a specific log entry to be persisted permanently in the history.
    *   `POST /api/dashboard/stats/`: Provides aggregate totals (API calls, videos) and chart data based on daily usage.

## Frontend Changes

1.  **Framework & Styling:**
    *   Integrated **Tailwind CSS v4** via Vite plugin for rapid, utility-first styling.
    *   Removed `index.css`'s monolithic custom CSS in favor of Tailwind classes, alongside the `lucide-react` icon library.

2.  **Complete UI Redesign:**
    *   Discarded the preliminary top-bar layout.
    *   Implemented a sleek, dark-themed layout featuring a slim left sidebar for navigation (`Sidebar.tsx`) and a top header (`Header.tsx`).

3.  **New Component Architecture:**
    *   **`DashboardView.tsx`**: The main analytics page. Includes:
        *   `ApiCallChart.tsx`: Dynamically drawn SVG line chart visualizing daily API calls.
        *   `KeyInsights.tsx`: Displays total processed videos versus total videos, and total API calls.
        *   `LogsTable.tsx`: Shows a live feed of the most recent requests.
    *   **`ApiTesterView.tsx`**: Advanced Postman-like tester.
        *   Replaced the arbitrary URL input box with a strictly controlled dropdown of preset endpoints.
        *   Dynamically provides JSON `bodyHints` when an endpoint is selected, eliminating the need for a separate 'ID' input field.
        *   Supports dynamic request header modification.
        *   "Save to DB" functionality securely persists the last request pair to the database.
    *   **`HistoryView.tsx`**:
        *   Fetches and renders logs explicitly marked as "saved".
        *   Includes a dark-mode optimized date filtering input to find past requests.

4.  **Cleanup & Build:**
    *   Refactored API service layer to interface smoothly with the new backend routing.
    *   Updated TypeScript type definitions.
    *   Deleted all outdated `src/components` (`RequestBuilder.tsx`, `VideoPanel.tsx`, etc.).
    *   Successfully executed production build (`npm run build`).

## API Tester & Background Processing Enhancements

1.  **Deletion Endpoints Added:**
    *   Implemented `CourseDeleteAPI` (`POST /api/courses/delete/`) for cascading hard deletion of courses.
    *   Implemented `VideoDeleteAPI` (`POST /api/videos/delete/`) for targeted video deletion by `course_id` and `video_id`.

2.  **API Tester Improvements:**
    *   Replaced the native HTML `<select>` dropdown in the header section with a fully custom, dark-themed styled dropdown supporting click-outside behaviors.
    *   Introduced a customizable **Base URL** input field, defaulting to `/api` to bypass browser CORS constraints when testing locally on different ports.
    *   Fixed a critical `404 Not Found` routing issue caused by a doubled `/api` path prefix mismatch between the frontend constants and the `api.ts` fetch service.
    *   Expanded `COMMON_HEADERS` with 7 additional organized HTTP standard headers.

3.  **Celery & Kombu Stability Fixes:**
    *   Fixed a known Python 3.12 Kombu `ChannelPromise` evaluation bug and circular `NameError` exceptions by dispatching async video processing tasks exclusively via `celery.current_app.send_task()`.
    *   Resolved `Connection refused` default fallback errors by explicitly exposing the `celery_app` instance inside `config/__init__.py`.
    *   Corrected task registration inside `autodiscover_tasks` to properly locate the `processing.py` module.
    *   Added a `@worker_ready` signal in `config/celery.py` to automatically detect and re-dispatch any lingering `SCHEDULED` video jobs across restarts.

4.  **Video Ingestion Resiliency:**
    *   Caught and mitigated missing metadata payloads from the Vimeo API integrations by strictly defaulting empty descriptions to `''`, preventing fatal MySQL `IntegrityError` NOT NULL constraints.

## Performance & Stability Fixes

1.  **Backend CPU Optimization:**
    *   Added `-threads 1` to all `ffmpeg` subprocess commands in `apps/core/services/transcriber.py`.
    *   Prevents concurrent Celery workers from attempting to consume all available CPU cores during simultaneous video audio extraction and chunk transcriptions, resolving entire system freezes.

2.  **Frontend Chrome Memory Validation:**
    *   Truncated `request_body` and `response_body` (maximum 2000 characters) inside `ApiCallLogSerializer` (`apps/core/api/serializers/dashboard_serializers.py`).
    *   Eliminates Chrome memory consumption spikes (OOM crashes) during the 10-second `DashboardView` dashboard polling loop when videos are actively processing and generating massive log payloads.

## System Optimization & Scalability Fixes (April 5, 2026)

1.  **Celery Worker Bottlenecks & OOM Preventions:**
    *   Tuned Celery settings for high-volume workloads (28GB RAM, 50-video batches).
    *   Increased `CELERY_WORKER_CONCURRENCY` to `4`.
    *   Set `CELERY_WORKER_PREFETCH_MULTIPLIER = 1` to prevent hidden double-loading of memory-intensive tasks.
    *   Added `CELERY_WORKER_MAX_TASKS_PER_CHILD = 10` to periodically recycle workers and implicitly clear memory leaks from long-running FAISS/OpenAI processes.
    *   Enforced hard and soft task time limits.

2.  **Course Aggregation Decoupling (Critical Fix):**
    *   Moved the `CourseAggregator.rebuild_if_stale` logic out of the inline video processing task.
    *   Dispatched course rebuilding as a separate dedicated background task (`rebuild_course_vectorstore_task`) using a 60-second countdown.
    *   This prevents the worker from accumulating and holding ~50 FAISS indexes in RAM simultaneously during bulk processing, resolving entire system freezes.

3.  **Startup Burst Mitigation:**
    *   Modified the `@worker_ready` signal in `config/celery.py` to stagger the re-dispatching of stuck `SCHEDULED` jobs with a 60-second delay per job, instead of firing all pending jobs simultaneously.

4.  **Dashboard API Call Truncation & Polling Reduction:**
    *   Truncated API logger request and response body lengths to `500` characters directly at the source React interface (`ApiTesterView.tsx`) before making the database write logging call, minimizing payload footprints per row.
    *   Throttled dashboard real-time data polling interval from 10 seconds to 30 seconds (`DashboardView.tsx`).
    *   Implemented `document.hidden` Page Visibility checks to entirely pause active polling when the dashboard browser tab is in the background.
    *   Implemented aggressive 7-day automatic pruning of the `ApiCallLog` database table for non-saved entries.
    *   Removed N+1 query execution inside the `DashboardLogsAPI` by leveraging list lengths over an explicit `.count()` call limit querying.

## Dashboard Enhancements & Task Management (April 5, 2026)

1.  **API Tester Complete Redesign:**
    *   **Tab State Persistence:** Modified `App.tsx` routing to keep all dashboard tabs simultaneously mounted via CSS `display: none` toggling. Navigating away from the API tester now flawlessly preserves entered parameters, body configurations, and response outputs.
    *   **Unified URL Bar:** Added an editable full-URL address bar that dynamically synchronizes with the predefined endpoint selector endpoint selection.
    *   **HTTP Method selector:** Implemented a new dropdown to freely switch HTTP methods (`GET`, `POST`, `PUT`, `DELETE`, etc.), featuring tailored color-coded UI badges.
    *   **Form Reset Capability:** Introduced a 'Trash/Clear' button utilizing `lucide-react` icons that instantly reverts URL paths, method selections, custom headers, JSON bodies, and response states back to initialization defaults.

2.  **Robust Video Queue Management:**
    *   Created a new comprehensive Django management command: `python manage.py purge_video_queue`.
    *   **Three-stage termination engine:** Safely coordinates immediate cancellation of running tasks by issuing `SIGTERM` revocation signals directly to the active Celery worker processes, completely purging the Redis message broker of queued task backlog, and uniformly resetting incomplete `SCHEDULED` / `PROCESSING` task instances within the MySQL database to `FAILED`.
    *   **Safe Execution Modes:** Equipped with `--dry-run` functionality for safe state preview and `--db-only` enforcement bypassing Celery API interactions entirely.

## Audio Transcription Parallelization & Optimization (April 6, 2026)

1.  **Parallel Transcription Engine:**
    *   Replaced sequential Whisper API requests with a ThreadPoolExecutor (5 concurrent workers).
    *   Added an exponential backoff retry mechanism (3 attempts) for increased reliability against API transient errors (429/5xx).
    *   Implemented glob-based chunk sorting to ensure perfect sequential reassembly of transcripts.

2.  **Fast Audio Splitting:**
    *   Migrated from iterative ffmpeg slicing (manual -ss / -t loops) to the ffmpeg **segment muxer**.
    *   The new approach slices the entire audio file into 10-minute chunks in a **single pass** using -c copy.
    *   Drastically reduces disk I/O and CPU overhead by avoiding repeated file re-scanning of extremely large media files.

3.  **Performance & Resource Efficiency:**
    *   Estimated reduction in processing time for large videos (>4 hours) from ~25 minutes to **~5 minutes** (5x speedup).
    *   Maintains low local resource footprint by strictly utilizing I/O-bound concurrency and offloading computational transcription to OpenAI servers.

## Temporal Cloud Orchestration Migration (April 7, 2026)

1.  **Architecture Transformation & Decoupling:**
    *   Transitioned the core overarching video processing pipeline from locally managed Celery workers to a resilient **Temporal Cloud** orchestrated workflow engine.
    *   Replaced fragile asynchronous task chains with deterministic state workflows (`VideoProcessingWorkflow`), ensuring step-level durability and automatic recovery semantics upon worker disruptions.

2.  **Workflow & Activity Segregation:**
    *   Implemented strict separation of orchestration (Workflows) from execution logic (Activities) within the newly established `apps.core.temporal` package module.
    *   Refactored original synchronous service utilities (Download, Audio Extraction, Whisper Transcription, FAISS Embedding) into distinct `@activity.defn` functions wrapped with robust heartbeat monitoring and execution timeouts.
    *   Integrated explicit Temporal Retry Policies to systematically handle network-bound transient errors strictly targeting Vimeo API ingestion and OpenAI vectorization limits.

3.  **Cross-Context View Dispatching Integration:**
    *   Abstracted Temporal client connections within `apps.core.temporal.client` introducing an async-to-sync coroutine dispatch bridge (`_run_async`).
    *   Replaced existing Celery `send_task` execution points across all unified REST hooks (`VideoCreateAPI`, `BulkVideoCreateAPI`, `VideoDeleteAPI`) allowing synchronous Django Views to trigger completely decoupled Temporal workflow initializations.
    *   Migrated large scale aggregation logic (`rebuild_course_vectorstore`) uniformly into an independent standalone `CourseRebuildWorkflow` safely triggered via child-workflow paradigms, mitigating cumulative Out-of-Memory (OOM) ingestion accumulation.

4.  **Operational Resilience & Fallbacks:**
    *   Deactivated the historical Celery `@worker_ready` redispatch signal logic returning an explicit early exit mapping to prevent dual-processing pipeline overlap, while preserving legacy logic blocks via commentary fallback structures.
    *   Introduced a dedicated custom Django management command `python manage.py run_temporal_worker` handling seamless CLI initialization loops polling against explicitly authenticated MTLS Temporal Cloud instances configured universally through `.env` namespace variables.

5.  **Django ORM Async-Safety Enhancements:**
    *   Resolved `SynchronousOnlyOperation` failures by deliberately converting asynchronous activity definitions back into standard standard definition scopes (`def` vs `async def`).
    *   Leveraged Temporal's built-in multi-threading models alongside Python's concurrent `ThreadPoolExecutor` context managers (`max_workers=4`) injected dynamically directly into the `Worker` configurations, ensuring seamless parallel network IO without violating strict Django ORM thread locality invariants.

6.  **Temporal Queue Recovery Utilities:**
    *   Created `python manage.py retry_failed_videos`, a fully featured CLI administration command capable of filtering historically bogged `FAILED`, `SCHEDULED`, and `IN_PROGRESS` task states from local database models.
    *   Designed with deep `--dry-run` and `--job-ids` inspection parameters to ensure robust pipeline resets, dynamically wiping legacy crash tracebacks while correctly proxying refreshed context payloads directly into the Temporal task broker.

7.  **Payload Serialization & Type Compatibility Fixes:**
    *   Resolved `RuntimeError: Failed decoding arguments` caused by strict Temporal JSON deserialization mismatches between external API outputs and workflow dataclass definitions.
    *   Implemented exhaustive defensive type coercion (`str()`, `int()`, `dict()`) across all activity return structures, ensuring that `null` values from Vimeo/OpenAI responses are correctly normalized to non-optional primitive defaults (e.g., empty strings or zeros) before crossing the Temporal wire.
