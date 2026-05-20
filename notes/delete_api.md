# Implementation Plan: Study Material Deletion API

This plan outlines the steps to implement a complete deletion API for Study Materials, ensuring that all database records and associated disk files (vectorstores, extracted texts, zips) are properly removed to avoid storage leaks.

## Proposed Changes

### `apps/core/api/views/study_material_views.py`

#### [MODIFY] `study_material_views.py`

Add a new view `StudyMaterialDeleteAPI` mapped to a new endpoint (e.g. `POST /api/study-materials/delete/` or `DELETE /api/study-materials/<id>/`).

The view will perform the following steps:

1. **Fetch Study Material**: Retrieve the `StudyMaterial` by ID.
2. **Delete Original Zip**: If `sm.file_path` exists on disk, `os.remove()` it.
3. **Delete Raw & Text Directory**: Calculate the base directory (`settings.MEDIA_ROOT/study_materials/<slug>`) and use `shutil.rmtree()` to remove all extracted raw files and converted `.txt` files.
4. **Delete Per-File Vectorstores**: Loop through `sm.files.all()`. For any `StudyMaterialFile` with a `vectorstore_path`, construct the absolute path and `shutil.rmtree()` the directory.
5. **Delete Merged Vectorstore**: If `sm.vectorstore_location` is set, construct the absolute path and `shutil.rmtree()` the directory.
6. **Delete Database Records**: Call `sm.delete()`, which will cascade and delete all associated `StudyMaterialFile` records automatically.
7. Return a success response.

### `apps/core/api/urls.py`

#### [MODIFY] `urls.py`

Add the new URL route for the deletion API:
`path('study-materials/<int:pk>/delete/', StudyMaterialDeleteAPI.as_view(), name='study_material_delete')`

### `dashboard/src/services/api.ts` & `dashboard/src/components/StudyMaterialsView.tsx` (Optional but recommended)

#### [MODIFY] `api.ts`

Add a `deleteStudyMaterial(id: number)` API function.

#### [MODIFY] `StudyMaterialsView.tsx`

Add a delete button (trash icon) to the UI next to each study material to trigger this API and update the state.

## Open Questions

> [!IMPORTANT]
> **Q1: Course Associations:** If a Study Material is currently merged into a Course (`sm.attached_to_courses.exists()`), should the API allow deletion? If we delete the SM, the Course will lose access to its content, but the Course's `merged_vectorstore_path` might still exist unless we also trigger a re-merge for the Course.
> _Recommendation:_ Block deletion and return an error if the SM is attached to any courses, requiring the user to detach/remove it from the course first. Alternatively, we can just allow it but it might cause the Course to behave unexpectedly until re-merged. How would you like to handle this?

> [!NOTE]
> **Q2: HTTP Method:** Following the pattern in your `urls.py` (e.g. `POST /api/courses/delete/`), should the endpoint be `POST /api/study-materials/delete/` with the ID in the body, or `DELETE /api/study-materials/<id>/delete/`?
> _Recommendation:_ Use `DELETE /api/study-materials/<id>/delete/` or match existing POST conventions if preferred.

## Verification Plan

- Call the deletion API with a valid Study Material ID.
- Verify that the API returns a 200 OK.
- Check the database to ensure the `StudyMaterial` and `StudyMaterialFile` records are gone.
- Check the filesystem to ensure the `study_materials/<slug>`, `study_materials_vectorstore/individual_vectorstores/<...>`, and `study_materials_vectorstore/complete_vectorstores/<...>` directories are completely removed.
