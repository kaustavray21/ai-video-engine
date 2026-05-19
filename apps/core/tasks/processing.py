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
    Execute the video processing pipeline for a ProcessingJob.

    Pipeline order:
        0. DEDUP  — if vectorstore already exists on disk → point & REUSED
        1. Vimeo transcript fast path — grab captions if available
        2. Fallback: Download video from Vimeo
        3. Fallback: Extract audio (ffmpeg)
        4. Fallback: Transcribe (OpenAI Whisper API)
        5. Create embeddings + FAISS vectorstore
        6. Cleanup media files (.mp4, .wav)
        7. Rebuild course-level vectorstore
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

    vimeo_id = video.vimeo_video_id

    try:
        # ── DEDUP: Check if vectorstore already exists for this vimeo_video_id ──
        shared_path = os.path.join('video_vectorstores', vimeo_id)
        shared_abs = os.path.join(media_root, shared_path)

        if (vimeo_id
                and os.path.isdir(shared_abs)
                and os.path.exists(os.path.join(shared_abs, 'index.faiss'))):
            logger.info(
                f'[DEDUP] Vectorstore exists at {shared_abs}. '
                f'Pointing instead of reprocessing.'
            )
            video.vectorstore_path = shared_path
            video.vectorstore_created = True
            video.status = 'ready'
            video.save(update_fields=[
                'vectorstore_path', 'vectorstore_created', 'status',
            ])

            job.mark_reused(source_info=f'disk:{shared_path}')

            # Still rebuild course vectorstore so this video is merged in
            rebuild_course_vectorstore_task.apply_async(
                args=[course.id], countdown=60,
            )
            logger.info(f'✅ Job {job_id} completed via REUSED path')
            return
        # ── END DEDUP ───────────────────────────────────────────────

        # ── Step 0: Try Vimeo transcript fast path ──────────────────
        transcript_text = None
        media_files_to_clean = []  # track files to delete in cleanup

        job.update_progress(3, 'checking_vimeo_captions')
        try:
            from apps.core.services.vimeo_transcript import VimeoTranscriptService
            vts = VimeoTranscriptService(vimeo_token=vimeo_token)
            vt_result = vts.fetch_transcript(vimeo_id)
        except Exception as e:
            logger.warning(f'Vimeo transcript check failed: {e}')
            vt_result = {'success': False}

        if vt_result.get('success'):
            logger.info('✅ Vimeo transcript found! Skipping download/audio/whisper.')
            transcript_text = vt_result['transcript_text']
            video.transcript_path = os.path.relpath(
                vt_result['transcript_path'], media_root
            )
            video.transcript_source = 'vimeo_captions'
            video.vimeo_caption_language = vt_result.get('language', '')
            video.save(update_fields=[
                'transcript_path', 'transcript_source', 'vimeo_caption_language',
            ])
            job.update_progress(60, 'vimeo_transcript_obtained')
        else:
            logger.info('Vimeo captions not available. Full pipeline.')
        # ── End Step 0 ─────────────────────────────────────────────

        # ── Steps 1-3: Full pipeline (only when fast path missed) ──
        if transcript_text is None:
            # ---- Step 1: Download ------------------------------------------------
            job.update_progress(5, 'downloading')
            video.status = 'downloading'
            video.save(update_fields=['status'])

            from apps.core.services.downloader import VimeoDownloader

            output_dir = os.path.join(media_root, 'live_videos')
            downloader = VimeoDownloader(vimeo_token=vimeo_token, output_dir=output_dir)

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
            media_files_to_clean.append(dl_result.video_file)
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
            media_files_to_clean.append(audio_path)
            job.update_progress(40, 'audio_extracted')

            # ---- Step 3: Transcribe ----------------------------------------------
            job.update_progress(45, 'transcribing')
            tx_result = transcriber.transcribe(audio_path)
            if not tx_result.success:
                raise Exception(f'Transcription failed: {tx_result.error}')

            transcript_text = tx_result.transcript
            video.transcript_path = os.path.relpath(tx_result.transcript_file, media_root)
            video.transcript_source = 'whisper'
            video.save(update_fields=['transcript_path', 'transcript_source'])
            job.update_progress(60, 'transcription_complete')
            logger.info(f'Transcription complete: {tx_result.segment_count} segments')

        # ── Step 4: Embeddings + vectorstore (runs for both paths) ──
        job.update_progress(65, 'embedding')
        video.status = 'embedding'
        video.save(update_fields=['status'])

        from apps.core.services.embedder import Embedder

        embedder = Embedder(openai_api_key=openai_key)

        # Global vectorstore path: keyed by vimeo_video_id, not DB ID
        vs_save_path = os.path.join(
            media_root, 'video_vectorstores', vimeo_id,
        )
        embed_result = embedder.create_vectorstore(
            transcript_text=transcript_text,
            save_path=vs_save_path,
            metadata={
                'video_id': video.id,
                'vimeo_video_id': vimeo_id,
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

        # ── Step 5: Cleanup media files (.mp4, .wav) ──────────────
        job.update_progress(90, 'cleanup')
        for fpath in media_files_to_clean:
            try:
                if fpath and os.path.exists(fpath):
                    os.remove(fpath)
                    logger.info(f'Cleaned up: {fpath}')
            except Exception as e:
                logger.warning(f'Cleanup failed (non-fatal): {e}')

        # ── Step 6: Mark complete + rebuild course vectorstore ─────
        job.processing_path = (
            'vimeo_transcript' if video.transcript_source == 'vimeo_captions'
            else 'full_pipeline'
        )
        job.processing_details = {
            'transcript_source': video.transcript_source,
            'vectorstore': {
                'chunks': embed_result.chunk_count,
                'path': vs_save_path,
            },
        }
        job.mark_completed()
        logger.info(f'Job {job_id} completed successfully ({job.processing_path})')

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


# Register study material tasks so Celery autodiscovery picks them up
from apps.core.tasks.study_material_tasks import process_study_material  # noqa: F401, E402
