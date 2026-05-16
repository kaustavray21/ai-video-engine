"""
Temporal activities for the AI Video Engine processing pipeline.

Each activity maps to one pipeline step:
  1. download_video          — Vimeo API download
  2. extract_and_transcribe  — ffmpeg audio extraction + OpenAI Whisper
  3. create_embeddings       — Text chunking + FAISS vectorstore creation
  4. cleanup_media_files     — Delete .mp4 and .wav files
  5. rebuild_course_vectorstore — Merge per-video FAISS indexes into course index
  6. mark_job_complete       — Mark ProcessingJob as completed
"""

import os
import logging
from dataclasses import dataclass, field
from typing import Optional

import django
from temporalio import activity

logger = logging.getLogger(__name__)


# ─── Input / Output dataclasses ───────────────────────────────────────────────
# Use dataclasses, not dicts — Temporal serializes these to JSON automatically.

@dataclass
class DownloadInput:
    job_id: int
    vimeo_video_id: str
    video_url: str
    video_id: int
    media_root: str

@dataclass
class DownloadOutput:
    video_file: str
    audio_path_placeholder: str   # derived: same path with .wav extension
    title: str
    description: str
    duration: int
    filesize: int
    metadata: dict = field(default_factory=dict)

@dataclass
class TranscribeInput:
    job_id: int
    video_file: str
    media_root: str

@dataclass
class TranscribeOutput:
    transcript: str
    transcript_file: str
    segment_count: int
    audio_path: str              # absolute path to .wav (for cleanup)

@dataclass
class EmbedInput:
    job_id: int
    video_id: int
    course_id: int
    video_title: str
    transcript: str
    media_root: str

@dataclass
class EmbedOutput:
    vectorstore_abs_path: str
    vectorstore_rel_path: str
    chunk_count: int

@dataclass
class CleanupInput:
    video_file: str
    audio_path: str

@dataclass
class RebuildCourseInput:
    course_id: int

@dataclass
class MarkCompleteInput:
    job_id: int
    video_id: int
    course_id: int
    chunk_count: int
    segment_count: int
    vectorstore_path: str
    video_file: str


# ─── Activities ────────────────────────────────────────────────────────────────

@activity.defn
def download_video(inp: DownloadInput) -> DownloadOutput:
    """Download Vimeo video via REST API. Updates Video and ProcessingJob in DB."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()

    from apps.core.models import ProcessingJob, Video
    from apps.core.services.downloader import VimeoDownloader
    from django.conf import settings

    job = ProcessingJob.objects.select_related('video__course').get(id=inp.job_id)
    video = job.video

    import re
    safe_course_title = re.sub(r'[^\w\s-]', '', video.course.title).strip().replace(' ', '_')

    job.update_progress(5, 'downloading')
    video.status = 'downloading'
    video.save(update_fields=['status'])

    activity.heartbeat('starting_download')

    output_dir = os.path.join(inp.media_root, 'live_videos', safe_course_title)
    downloader = VimeoDownloader(
        vimeo_token=settings.VIMEO_TOKEN,
        output_dir=output_dir,
    )

    result = downloader.download(inp.vimeo_video_id)
    if not result.success:
        raise Exception(f'Download failed: {result.error}')

    activity.heartbeat('download_complete')

    video.local_path = os.path.relpath(result.video_file, inp.media_root)
    video.title = result.title or video.title
    video.description = result.description or ''
    video.duration_seconds = result.duration
    video.metadata = result.metadata or {}
    video.save(update_fields=[
        'local_path', 'title', 'description', 'duration_seconds', 'metadata',
    ])
    job.update_progress(25, 'download_complete')

    audio_placeholder = os.path.splitext(result.video_file)[0] + '.wav'

    return DownloadOutput(
        video_file=str(result.video_file or ''),
        audio_path_placeholder=str(audio_placeholder or ''),
        title=str(result.title or ''),
        description=str(result.description or ''),
        duration=int(result.duration or 0),
        filesize=int(result.filesize or 0),
        metadata=dict(result.metadata) if result.metadata else {},
    )


@activity.defn
def extract_and_transcribe(inp: TranscribeInput) -> TranscribeOutput:
    """
    Extract audio from video with ffmpeg, then transcribe with OpenAI Whisper.
    Combined into one activity so the .wav file stays on the same worker process
    that created it — avoids cross-worker file path issues.
    """
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()

    from apps.core.models import ProcessingJob, Video
    from apps.core.services.transcriber import Transcriber
    from django.conf import settings

    job = ProcessingJob.objects.select_related('video__course').get(id=inp.job_id)
    video = job.video

    import re
    safe_course_title = re.sub(r'[^\w\s-]', '', video.course.title).strip().replace(' ', '_')
    vimeo_id = video.vimeo_video_id
    transcript_filename = f'{vimeo_id}_transcript.txt'
    output_txt_path = os.path.join(inp.media_root, 'live_videos', safe_course_title, transcript_filename)

    transcriber = Transcriber(openai_api_key=settings.OPENAI_API_KEY)

    # ── Audio extraction ──
    activity.heartbeat('extracting_audio')
    job.update_progress(30, 'transcribing')
    video.status = 'transcribing'
    video.save(update_fields=['status'])

    audio_path = transcriber.extract_audio(inp.video_file)
    if not audio_path:
        raise Exception('Audio extraction failed — check ffmpeg is installed')

    video.audio_path = os.path.relpath(audio_path, inp.media_root)
    video.save(update_fields=['audio_path'])
    job.update_progress(40, 'audio_extracted')

    # ── Transcription ──
    activity.heartbeat('transcribing')
    job.update_progress(45, 'transcribing')

    tx_result = transcriber.transcribe(audio_path, output_txt_path=output_txt_path)
    if not tx_result.success:
        raise Exception(f'Transcription failed: {tx_result.error}')

    video.transcript_path = os.path.relpath(tx_result.transcript_file, inp.media_root)
    video.save(update_fields=['transcript_path'])
    job.update_progress(60, 'transcription_complete')

    activity.heartbeat('transcription_complete')

    return TranscribeOutput(
        transcript=str(tx_result.transcript or ''),
        transcript_file=str(tx_result.transcript_file or ''),
        segment_count=int(tx_result.segment_count or 0),
        audio_path=str(audio_path or ''),
    )


@activity.defn
def create_embeddings(inp: EmbedInput) -> EmbedOutput:
    """Chunk transcript text and build a per-video FAISS vectorstore."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()

    from apps.core.models import ProcessingJob, Video
    from apps.core.services.embedder import Embedder
    from django.conf import settings

    job = ProcessingJob.objects.select_related('video').get(id=inp.job_id)
    video = job.video

    video.status = 'embedding'
    video.save(update_fields=['status'])
    job.update_progress(65, 'embedding')

    activity.heartbeat('creating_embeddings')

    embedder = Embedder(openai_api_key=settings.OPENAI_API_KEY)
    vs_save_path = os.path.join(
        inp.media_root,
        f'course_{inp.course_id}',
        'vectorstore',
        f'video_{inp.video_id}',
    )

    result = embedder.create_vectorstore(
        transcript_text=inp.transcript,
        save_path=vs_save_path,
        metadata={
            'video_id': inp.video_id,
            'course_id': inp.course_id,
            'video_title': inp.video_title,
        },
    )
    if not result.success:
        raise Exception(f'Embedding failed: {result.error}')

    activity.heartbeat('embeddings_complete')

    vs_rel_path = os.path.relpath(vs_save_path, inp.media_root)
    video.vectorstore_path = vs_rel_path
    video.save(update_fields=['vectorstore_path'])
    job.update_progress(85, 'vectorstore_created')

    return EmbedOutput(
        vectorstore_abs_path=str(vs_save_path or ''),
        vectorstore_rel_path=str(vs_rel_path or ''),
        chunk_count=int(result.chunk_count or 0),
    )


@activity.defn
def cleanup_media_files(inp: CleanupInput) -> None:
    """Delete .mp4 and .wav after FAISS index is persisted. Non-fatal on error."""
    for fpath in [inp.video_file, inp.audio_path]:
        try:
            if fpath and os.path.exists(fpath):
                os.remove(fpath)
                logger.info(f'Cleaned up: {fpath}')
        except Exception as e:
            logger.warning(f'Cleanup failed (non-fatal): {e}')


@activity.defn
def rebuild_course_vectorstore(inp: RebuildCourseInput) -> str:
    """
    Merge all per-video FAISS indexes into the course-level index.
    This is memory-intensive — it runs as a separate workflow/activity
    so this worker fully releases RAM from the video pipeline first.
    """
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()

    from apps.core.models import Course
    from apps.core.services.aggregator import CourseAggregator
    from django.conf import settings

    course = Course.objects.get(id=inp.course_id)
    aggregator = CourseAggregator(openai_api_key=settings.OPENAI_API_KEY)

    activity.heartbeat('rebuilding_course_vectorstore')

    result = aggregator.force_rebuild(course)

    logger.info(
        f'Course rebuild for "{course.title}": {result.status} '
        f'({result.videos_merged} merged, {result.videos_skipped} skipped)'
    )
    return result.status


@activity.defn
def mark_job_complete(inp: MarkCompleteInput) -> None:
    """Mark ProcessingJob as completed and update Video.vectorstore_created."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()

    from apps.core.models import ProcessingJob

    job = ProcessingJob.objects.select_related('video__course').get(id=inp.job_id)
    job.processing_details = {
        'vectorstore': {
            'chunks': inp.chunk_count,
            'path': inp.vectorstore_path,
        },
        'transcript': {'segments': inp.segment_count},
    }
    job.mark_completed()   # sets video.vectorstore_created=True, course.update_statistics()
