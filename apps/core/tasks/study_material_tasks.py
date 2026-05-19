"""
Celery tasks for study material processing.

process_study_material — main pipeline task (resumable on retry).
retry_study_material   — re-queues a failed SM from the last checkpoint.
"""

import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

logger = logging.getLogger(__name__)


@shared_task(bind=True, soft_time_limit=14400, time_limit=15000, max_retries=0)
def process_study_material(self, study_material_id: int):
    """
    Resumable pipeline — skips already-completed files on retry.

    Phases (see StudyMaterialProcessor):
      1. Discovery  — extract zip, create StudyMaterialFile records
      2. Per-file   — convert + embed each file individually
      3. Merge      — merge all per-file VSs into full SM vectorstore
      4. Cleanup    — delete zip + raw files
    """
    from apps.core.models.study_material import StudyMaterial
    from apps.core.services.study_material_processor import StudyMaterialProcessor

    logger.info(f'[Task] START process_study_material id={study_material_id}')

    try:
        sm = StudyMaterial.objects.get(pk=study_material_id)
    except StudyMaterial.DoesNotExist:
        logger.error(f'[Task] StudyMaterial id={study_material_id} not found')
        return {'status': 'error', 'error': 'StudyMaterial not found'}

    try:
        processor = StudyMaterialProcessor()
        result = processor.run(sm)

        if result.success:
            logger.info(
                f'[Task] DONE process_study_material id={study_material_id} — '
                f'{result.processed_files}/{result.files_count} files, '
                f'VS at {result.vectorstore_location}'
            )
        else:
            logger.error(
                f'[Task] FAILED process_study_material id={study_material_id}: {result.error}'
            )

        return {
            'status': 'completed' if result.success else 'failed',
            'study_material_id': study_material_id,
            'files_count': result.files_count,
            'processed_files': result.processed_files,
            'vectorstore_location': result.vectorstore_location,
            'error': result.error,
        }

    except SoftTimeLimitExceeded:
        logger.warning(
            f'[Task] Soft time limit (14400s) exceeded for SM id={study_material_id}. '
            f'Completed files are checkpointed — use /retry/ to resume.'
        )
        StudyMaterial.objects.filter(pk=study_material_id).update(
            status=StudyMaterial.STATUS_FAILED,
            error_log='Soft time limit exceeded — retry to resume from last checkpoint',
        )
        return {
            'status': 'failed',
            'study_material_id': study_material_id,
            'error': 'soft_time_limit_exceeded',
        }

    except Exception as exc:
        logger.exception(f'[Task] Unexpected error for SM id={study_material_id}: {exc}')
        StudyMaterial.objects.filter(pk=study_material_id).update(
            status=StudyMaterial.STATUS_FAILED,
            error_log=str(exc),
        )
        raise


@shared_task
def retry_study_material(study_material_id: int):
    """
    Re-queue a failed study material.
    Phase 2 will skip already-completed files — only pending/failed ones are retried.
    """
    from apps.core.models.study_material import StudyMaterial

    logger.info(f'[Task] Retrying SM id={study_material_id}')

    updated = StudyMaterial.objects.filter(pk=study_material_id).update(
        status=StudyMaterial.STATUS_PROCESSING,
        error_log='',
    )
    if not updated:
        logger.error(f'[Task] SM id={study_material_id} not found for retry')
        return {'status': 'error', 'error': 'StudyMaterial not found'}

    process_study_material.delay(study_material_id)
    return {'status': 'queued', 'study_material_id': study_material_id}
