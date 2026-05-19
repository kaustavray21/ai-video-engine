# tasks package
from .processing import process_video_task, rebuild_course_vectorstore_task  # noqa: F401 — Celery task registration
from .study_material_tasks import process_study_material, retry_study_material  # noqa: F401 — Celery task registration
