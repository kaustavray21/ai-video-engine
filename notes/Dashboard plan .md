# Dashboard V2 — Complete Redesign with Persistence

Redesign the React dashboard based on the user's `dashboard.tsx` reference file. This involves a complete UI overhaul (left sidebar, 3 views), new backend models for API call tracking, and Tailwind CSS integration.

## User Review Required

> [!IMPORTANT]
> This is a significant rewrite of the entire frontend + new backend models. The old top-toolbar dashboard will be fully replaced.

> [!WARNING]
> **Tailwind CSS**: The reference file uses Tailwind utility classes extensively. This plan adds Tailwind to the Vite project. If you prefer to keep vanilla CSS, say so and I'll convert all classes manually.

> [!IMPORTANT]
> **API redesign — ID in body, not URL**: All endpoints that previously took `{id}` in the URL path now accept `id` in the JSON body via POST. This simplifies the dashboard UI — no parameterized URLs, no secondary ID input. All requests go through the same flow: select endpoint → type body → send.
>
> **Fixed API endpoints (all simplified):**
> - `POST /api/courses/` — Create course (body: `{"title": "..."}`) 
> - `POST /api/courses/list/` — List courses (no body)
> - `POST /api/courses/detail/` — Course detail (body: `{"id": 5}`)
> - `POST /api/courses/status/` — Course status (body: `{"id": 5}`)
> - `POST /api/courses/videos/` — Course videos (body: `{"id": 5}`)
> - `POST /api/videos/` — Add video (body: `{"course_id": 1, "video_url": "..."}`) 
> - `POST /api/videos/status/` — Video status (body: `{"id": 3}`)
> - `POST /api/query/video/` — Query video (body: `{"video_id": 3, "question": "..."}`) 
> - `POST /api/query/course/` — Query course (body: `{"course_id": 1, "question": "..."}`) 
> - `POST /api/dashboard/log/` — Log API call
> - `POST /api/dashboard/logs/` — List logs (body: `{"date": "2026-03-30"}`)
> - `POST /api/dashboard/stats/` — Dashboard stats

---

## Proposed Changes

### Backend — New Model: `ApiCallLog`

A new model to persist every API call made through the dashboard. Serves two purposes:
1. **Logs table** on the Dashboard view (showing every request)
2. **Chart data** (aggregate daily API call counts)
3. **Key Insights** (total API calls, total videos processed)

---

#### [NEW] [api_log.py](file:///home/ricky/VScode/projects/python/Django/testings%20and%20implementation/ai_video_engine/apps/core/models/api_log.py)

```python
class ApiCallLog(models.Model):
    method        # CharField (GET/POST/PUT/PATCH/DELETE)
    endpoint      # CharField (the URL path)
    request_body  # TextField (JSON body, blank for GET)
    response_body # TextField (truncated response, max 10KB)
    status_code   # IntegerField
    status_text   # CharField
    latency_ms    # IntegerField
    saved         # BooleanField (True when user clicks "Save to DB")
    created_at    # DateTimeField (auto)
```

- Indexed on `created_at` and `saved` for fast queries
- Every API call auto-creates a log (for chart + logs)
- The `saved` flag differentiates explicitly saved requests (for History)

---

#### [MODIFY] [\_\_init\_\_.py](file:///home/ricky/VScode/projects/python/Django/testings%20and%20implementation/ai_video_engine/apps/core/models/__init__.py)

Add `ApiCallLog` to the models package exports.

---

#### [MODIFY] [admin.py](file:///home/ricky/VScode/projects/python/Django/testings%20and%20implementation/ai_video_engine/apps/core/admin.py)

Register `ApiCallLog` in Django admin.

---

### Backend — New API Endpoints

#### [NEW] [dashboard_views.py](file:///home/ricky/VScode/projects/python/Django/testings%20and%20implementation/ai_video_engine/apps/core/api/views/dashboard_views.py)

| Endpoint | Method | Description |
|---|---|---|
| `/api/dashboard/log/` | POST | Auto-log an API call (called by frontend after every request) |
| `/api/dashboard/logs/` | GET | List logs, query params: `?date=2026-03-30&saved_only=true` |
| `/api/dashboard/logs/{id}/save/` | PATCH | Mark a log entry as "saved" (Save to DB button) |
| `/api/dashboard/stats/` | GET | Aggregate stats: total API calls, total videos, daily chart data (last 14 days) |

#### [NEW] [dashboard_serializers.py](file:///home/ricky/VScode/projects/python/Django/testings%20and%20implementation/ai_video_engine/apps/core/api/serializers/dashboard_serializers.py)

Serializers for `ApiCallLog` create and list operations.

#### [MODIFY] [urls.py](file:///home/ricky/VScode/projects/python/Django/testings%20and%20implementation/ai_video_engine/apps/core/api/urls.py)

- Add the 4 new dashboard endpoints
- **Remove all `<int:course_id>` and `<int:video_id>` URL segments**
- Change from `courses/<int:course_id>/` → `courses/detail/`
- Change from `courses/<int:course_id>/status/` → `courses/status/`
- Change from `courses/<int:course_id>/videos/` → `courses/videos/`
- Change from `videos/<int:video_id>/status/` → `videos/status/`

---

### Backend — Modify Existing Views (ID from body)

All views that currently extract `course_id` or `video_id` from URL kwargs will be updated to read `id` from `request.data` (JSON body) instead.

#### [MODIFY] [course_views.py](file:///home/ricky/VScode/projects/python/Django/testings%20and%20implementation/ai_video_engine/apps/core/api/views/course_views.py)

- `CourseDetailAPI`: Change `get(request, course_id)` → `post(request)`, read `id` from `request.data`
- `CourseListCreateAPI.get()` → move to a separate `CourseListAPI.post()` at `/courses/list/`

#### [MODIFY] [video_views.py](file:///home/ricky/VScode/projects/python/Django/testings%20and%20implementation/ai_video_engine/apps/core/api/views/video_views.py)

- `VideoListCreateAPI.get()` → `post(request)`, read `id` from `request.data` for course_id

#### [MODIFY] [status_views.py](file:///home/ricky/VScode/projects/python/Django/testings%20and%20implementation/ai_video_engine/apps/core/api/views/status_views.py)

- `VideoStatusAPI`: Change `get(request, video_id)` → `post(request)`, read `id` from `request.data`
- `CourseStatusAPI`: Change `get(request, course_id)` → `post(request)`, read `id` from `request.data`

---

### Frontend — Complete Redesign

#### Dependencies to add

- `tailwindcss` + `@tailwindcss/vite` (Tailwind v4 Vite plugin)
- `lucide-react` (icon library used in the reference)

#### [DELETE] Old components

All existing components in `src/components/` will be replaced:
- `RequestBuilder.tsx`, `VideoPanel.tsx`, `CoursePanel.tsx`, `QueryPanel.tsx`, `ResponseViewer.tsx`

#### [DELETE] Old CSS

`src/index.css` — replaced with Tailwind + minimal custom CSS

---

#### New Component Structure

```
src/
├── App.tsx                          # Root: sidebar + header + active view
├── main.tsx                         # Entry (no change)
├── index.css                        # Tailwind imports + custom vars
├── types/index.ts                   # Updated types
├── services/api.ts                  # Updated API layer
├── constants/endpoints.ts           # Fixed API endpoint list
├── components/
│   ├── Sidebar.tsx                  # Left icon sidebar nav
│   ├── Header.tsx                   # Top header bar
│   ├── DashboardView.tsx            # Dashboard tab (chart, logs, insights)
│   ├── ApiTesterView.tsx            # API Tester tab (method, URL, headers, body, response)
│   ├── HistoryView.tsx              # History tab (date filter, saved request cards)
│   ├── ApiCallChart.tsx             # SVG line chart for daily API calls
│   ├── LogsTable.tsx                # Recent logs table
│   └── KeyInsights.tsx              # Stats cards (total videos, total API calls)
```

---

#### [NEW] [constants/endpoints.ts](file:///home/ricky/VScode/projects/python/Django/testings%20and%20implementation/ai_video_engine/dashboard/src/constants/endpoints.ts)

Fixed API endpoint list for dropdown. **All endpoints are POST** — no URL parameters:

```typescript
export const API_ENDPOINTS = [
  { method: 'POST', path: '/api/courses/',          label: 'Create Course',  bodyHint: '{"title": "My Course", "description": ""}' },
  { method: 'POST', path: '/api/courses/list/',     label: 'List Courses',   bodyHint: '' },
  { method: 'POST', path: '/api/courses/detail/',   label: 'Course Detail',  bodyHint: '{"id": 1}' },
  { method: 'POST', path: '/api/courses/status/',   label: 'Course Status',  bodyHint: '{"id": 1}' },
  { method: 'POST', path: '/api/courses/videos/',   label: 'Course Videos',  bodyHint: '{"id": 1}' },
  { method: 'POST', path: '/api/videos/',           label: 'Add Video',      bodyHint: '{"course_id": 1, "video_url": "https://vimeo.com/..."}' },
  { method: 'POST', path: '/api/videos/status/',    label: 'Video Status',   bodyHint: '{"id": 1}' },
  { method: 'POST', path: '/api/query/video/',      label: 'Query Video',    bodyHint: '{"video_id": 1, "question": "What is this about?"}' },
  { method: 'POST', path: '/api/query/course/',     label: 'Query Course',   bodyHint: '{"course_id": 1, "question": "Summarize all topics"}' },
];
```

**Body hints**: When the user selects an endpoint, the Body textarea auto-fills with the `bodyHint` as a placeholder — showing exactly what JSON to send. No separate ID field needed.

#### [MODIFY] [App.tsx](file:///home/ricky/VScode/projects/python/Django/testings%20and%20implementation/ai_video_engine/dashboard/src/App.tsx)

Root component with:
- Left `<Sidebar />` (icon-only, 64px wide)
- Right content area with `<Header />` + active view
- State: `activeTab` ('dashboard' | 'api' | 'history')

#### [NEW] [Sidebar.tsx](file:///home/ricky/VScode/projects/python/Django/testings%20and%20implementation/ai_video_engine/dashboard/src/components/Sidebar.tsx)

- `LayoutGrid` → Dashboard
- `Activity` → API Tester
- `Clock` → History
- Active tab: orange `#f05a28` background
- Hexagon logo at top

#### [NEW] [Header.tsx](file:///home/ricky/VScode/projects/python/Django/testings%20and%20implementation/ai_video_engine/dashboard/src/components/Header.tsx)

- Dynamic title based on active tab
- "AI Assistant" button (decorative for now)

#### [NEW] [DashboardView.tsx](file:///home/ricky/VScode/projects/python/Django/testings%20and%20implementation/ai_video_engine/dashboard/src/components/DashboardView.tsx)

12-column grid layout:
- **Left (8 cols)**: API Calls chart + Logs table
- **Right (4 cols)**: Key Insights + Data Sources (shows courses) + API Test code snippet

Fetches real data from:
- `GET /api/dashboard/stats/` → chart data + totals
- `GET /api/dashboard/logs/?limit=4` → recent logs

#### [NEW] [ApiTesterView.tsx](file:///home/ricky/VScode/projects/python/Django/testings%20and%20implementation/ai_video_engine/dashboard/src/components/ApiTesterView.tsx)

Exact replica of the reference `api` tab:
- **URL bar**: Dropdown `<select>` of fixed endpoints (from `endpoints.ts`). All endpoints are POST — method is always POST.
- **No ID field needed**: The ID is part of the JSON body (e.g. `{"id": 5}`). When the user selects an endpoint, the Body textarea auto-fills with the `bodyHint` placeholder.
- **Headers**: `datalist` with common Postman headers (Accept, Authorization, Content-Type, etc.), add/remove rows with + / X buttons
- **Body**: JSON textarea — always enabled since all endpoints are POST
- **Response**: Status badge + "Save to DB" button + response textarea (green text)
- After every send: auto-POST to `/api/dashboard/log/` in the background

#### [NEW] [HistoryView.tsx](file:///home/ricky/VScode/projects/python/Django/testings%20and%20implementation/ai_video_engine/dashboard/src/components/HistoryView.tsx)

- Date filter input (dark theme)
- Fetches from `GET /api/dashboard/logs/?saved_only=true&date=...`
- Request/Response cards with method badges (color-coded)

#### [MODIFY] [services/api.ts](file:///home/ricky/VScode/projects/python/Django/testings%20and%20implementation/ai_video_engine/dashboard/src/services/api.ts)

Add new functions:
- `logApiCall(data)` — POST to `/api/dashboard/log/`
- `fetchLogs(params)` — GET from `/api/dashboard/logs/`
- `saveLogEntry(id)` — PATCH to `/api/dashboard/logs/{id}/save/`
- `fetchDashboardStats()` — GET from `/api/dashboard/stats/`

#### [MODIFY] [types/index.ts](file:///home/ricky/VScode/projects/python/Django/testings%20and%20implementation/ai_video_engine/dashboard/src/types/index.ts)

Add types:
- `ApiCallLog` (matches backend model)
- `DashboardStats` (total_api_calls, total_videos, daily_chart_data)
- `ApiEndpoint` (method, path, label, hasId)

---

## Data Flow

```
User sends request (API Tester)
    │
    ├── fetch(endpoint) → show response
    │
    └── POST /api/dashboard/log/ (auto, background)
            │
            ├── Creates ApiCallLog (saved=false)
            └── Increments stats (chart + Key Insights)

User clicks "Save to DB"
    │
    └── PATCH /api/dashboard/logs/{id}/save/
            │
            └── Sets saved=true → appears in History tab

Dashboard view loads
    │
    ├── GET /api/dashboard/stats/  → chart + totals
    └── GET /api/dashboard/logs/?limit=4 → logs table

History view loads
    │
    └── GET /api/dashboard/logs/?saved_only=true&date=... → cards
```

---

## Open Questions

> [!IMPORTANT]
> **Tailwind CSS version**: The reference uses Tailwind utility classes. Should I use **Tailwind v4** (latest, uses `@tailwindcss/vite` plugin) or keep vanilla CSS and manually replicate every class? Tailwind v4 is the cleanest approach for matching the reference exactly.

> [!IMPORTANT]
> **Data Sources section**: The reference shows "Weibo", "Dow Jones", "VKontakte" as placeholder data sources. Should I replace these with actual courses from the database (fetched from `GET /api/courses/`)? Or leave as decorative placeholders?

> [!IMPORTANT]
> **API Test code snippet**: The reference shows a static code snippet (Python/JS/Go/Java tabs). Should I keep this as a static decorative element, or generate actual code snippets based on the last API call made?

---

## Verification Plan

### Automated
1. `npx tsc --noEmit` — TypeScript compiles clean
2. `npm run build` — Vite builds successfully
3. `python manage.py makemigrations` — migration created for ApiCallLog
4. `python manage.py migrate` — applies cleanly
5. `python manage.py check` — Django system check passes

### Manual (Browser)
1. Open `http://127.0.0.1:8000/dashboard/`
2. Verify sidebar navigation between 3 tabs
3. API Tester: select endpoint from dropdown, send request, verify response
4. Verify log auto-created in DB (check Dashboard logs table)
5. Click "Save to DB" → verify entry appears in History tab
6. History: filter by date → verify filter works
7. Dashboard: verify chart shows real data, Key Insights shows correct totals
