"""
Celery tasks for async video processing pipeline.

Extracted from: api/live_video_processor.py (process_video_job, lines 414-538)

Pipeline: download → extract audio → transcribe → embed → store vectorstore
          → cleanup media → rebuild course vectorstore
"""

import os
import logging

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_video_task(self, job_id: int):
    """
    Execute the full video processing pipeline for a ProcessingJob.

    Steps:
        1. Download video from Vimeo
        2. Extract audio (ffmpeg)
        3. Transcribe (OpenAI Whisper API)
        4. Create embeddings + FAISS vectorstore
        5. Cleanup media files (.mp4, .wav)
        6. Rebuild course-level vectorstore if stale
    """
    from apps.core.models import ProcessingJob

    try:
        job = ProcessingJob.objects.select_related('video__course').get(id=job_id)
    except ProcessingJob.DoesNotExist:
        logger.error(f'ProcessingJob {job_id} not found')
        return

    video = job.video
    course = video.course

    logger.info(f'Starting pipeline for job {job_id} — video "{video.title}"')
    job.mark_started()

    openai_key = settings.OPENAI_API_KEY
    vimeo_token = settings.VIMEO_TOKEN
    media_root = str(settings.MEDIA_ROOT)

    try:
        # ---- Step 1: Download ------------------------------------------------
        job.update_progress(5, 'downloading')
        video.status = 'downloading'
        video.save(update_fields=['status'])

        from apps.core.services.downloader import VimeoDownloader

        output_dir = os.path.join(media_root, 'live_videos')
        downloader = VimeoDownloader(vimeo_token=vimeo_token, output_dir=output_dir)

        vimeo_id = video.vimeo_video_id
        if not vimeo_id:
            vimeo_id = downloader.extract_video_id(video.video_url) or ''

        dl_result = downloader.download(vimeo_id)
        if not dl_result.success:
            raise Exception(f'Download failed: {dl_result.error}')

        video.local_path = os.path.relpath(dl_result.video_file, media_root)
        video.title = dl_result.title or video.title
        video.description = dl_result.description or ''
        video.duration_seconds = dl_result.duration
        video.metadata = dl_result.metadata or {}
        video.save(update_fields=[
            'local_path', 'title', 'description', 'duration_seconds', 'metadata',
        ])
        job.update_progress(25, 'download_complete')
        logger.info(f'Download complete: {dl_result.video_file}')

        # ---- Step 2: Extract audio -------------------------------------------
        job.update_progress(30, 'transcribing')
        video.status = 'transcribing'
        video.save(update_fields=['status'])

        from apps.core.services.transcriber import Transcriber

        transcriber = Transcriber(openai_api_key=openai_key)
        audio_path = transcriber.extract_audio(dl_result.video_file)
        if not audio_path:
            raise Exception('Audio extraction failed')

        video.audio_path = os.path.relpath(audio_path, media_root)
        video.save(update_fields=['audio_path'])
        job.update_progress(40, 'audio_extracted')

        # ---- Step 3: Transcribe ----------------------------------------------
        job.update_progress(45, 'transcribing')
        tx_result = transcriber.transcribe(audio_path)
        if not tx_result.success:
            raise Exception(f'Transcription failed: {tx_result.error}')

        video.transcript_path = os.path.relpath(tx_result.transcript_file, media_root)
        video.save(update_fields=['transcript_path'])
        job.update_progress(60, 'transcription_complete')
        logger.info(f'Transcription complete: {tx_result.segment_count} segments')

        # ---- Step 4: Embeddings + vectorstore --------------------------------
        job.update_progress(65, 'embedding')
        video.status = 'embedding'
        video.save(update_fields=['status'])

        from apps.core.services.embedder import Embedder

        embedder = Embedder(openai_api_key=openai_key)

        vs_save_path = os.path.join(
            media_root,
            f'course_{course.id}',
            'vectorstore',
            f'video_{video.id}',
        )
        embed_result = embedder.create_vectorstore(
            transcript_text=tx_result.transcript,
            save_path=vs_save_path,
            metadata={
                'video_id': video.id,
                'course_id': course.id,
                'video_title': video.title,
            },
        )
        if not embed_result.success:
            raise Exception(f'Embedding failed: {embed_result.error}')

        video.vectorstore_path = os.path.relpath(vs_save_path, media_root)
        video.save(update_fields=['vectorstore_path'])
        job.update_progress(85, 'vectorstore_created')
        logger.info(f'Vectorstore created: {embed_result.chunk_count} chunks')

        # ---- Step 5: Cleanup media files (.mp4, .wav) ------------------------
        job.update_progress(90, 'cleanup')
        for fpath in [dl_result.video_file, audio_path]:
            try:
                if fpath and os.path.exists(fpath):
                    os.remove(fpath)
                    logger.info(f'Cleaned up: {fpath}')
            except Exception as e:
                logger.warning(f'Cleanup failed (non-fatal): {e}')

        # ---- Step 6: Mark complete + rebuild course vectorstore ---------------
        job.processing_details = {
            'download': {'file': dl_result.video_file, 'size': dl_result.filesize},
            'transcript': {'segments': tx_result.segment_count},
            'vectorstore': {'chunks': embed_result.chunk_count, 'path': vs_save_path},
        }
        job.mark_completed()
        logger.info(f'Job {job_id} completed successfully')

        # Rebuild course-level vectorstore as a separate queued task.
        # IMPORTANT: do NOT run this inline — at scale (50 videos), the aggregator
        # loads ALL prior video FAISS indexes into this worker's RAM simultaneously,
        # causing OOM. Running it as a separate task ensures it starts only after
        # this task has fully exited and freed its memory.
        rebuild_course_vectorstore_task.apply_async(
            args=[course.id],
            countdown=60,  # 60s delay so this worker can fully clean up first
        )
        logger.info(
            f'Course aggregation for course {course.id} queued as background task '
            f'(starts in 60s)'
        )


    except Exception as e:
        logger.exception(f'Job {job_id} failed: {e}')
        job.mark_failed(error_message=str(e))

        # Retry if allowed
        if job.can_retry:
            job.retry_count += 1
            job.save(update_fields=['retry_count'])
            raise self.retry(exc=e)


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def rebuild_course_vectorstore_task(self, course_id: int):
    """
    Rebuild the course-level FAISS vectorstore.

    Called after video deletion or whenever the course index needs refreshing.
    """
    from apps.core.models import Course

    try:
        course = Course.objects.get(id=course_id)
    except Course.DoesNotExist:
        logger.error(f'Course {course_id} not found for vectorstore rebuild')
        return

    openai_key = settings.OPENAI_API_KEY

    try:
        from apps.core.services.aggregator import CourseAggregator
        aggregator = CourseAggregator(openai_api_key=openai_key)
        result = aggregator.force_rebuild(course)
        logger.info(
            f'Course vectorstore rebuild for "{course.title}": '
            f'{result.status} ({result.videos_merged} merged, '
            f'{result.videos_skipped} skipped)'
        )
    except Exception as e:
        logger.exception(f'Course vectorstore rebuild failed for course {course_id}: {e}')
        raise self.retry(exc=e)
