"""
Temporal workflow definitions for the AI Video Engine.

VideoProcessingWorkflow orchestrates the full pipeline:
    download → transcribe → embed → mark complete → cleanup → [child] course rebuild

CourseRebuildWorkflow runs separately to avoid OOM from merging all FAISS indexes
while the video pipeline memory is still in use.
"""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from apps.core.temporal.activities import (
        DownloadInput, DownloadOutput,
        TranscribeInput, TranscribeOutput,
        EmbedInput, EmbedOutput,
        CleanupInput, RebuildCourseInput,
        MarkCompleteInput,
        download_video,
        extract_and_transcribe,
        create_embeddings,
        cleanup_media_files,
        rebuild_course_vectorstore,
        mark_job_complete,
    )


@dataclass
class VideoProcessingInput:
    job_id: int
    video_id: int
    course_id: int
    vimeo_video_id: str
    video_url: str
    video_title: str
    media_root: str


# Retry policy for network/API-heavy steps.
# 3 attempts, exponential backoff starting at 30s.
# ValueError is non-retryable (bad input, not transient).
_network_retry = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=10),
    non_retryable_error_types=['ValueError'],
)

# Cleanup is best-effort — 2 attempts, no long wait
_cleanup_retry = RetryPolicy(
    maximum_attempts=2,
    initial_interval=timedelta(seconds=5),
)


@workflow.defn
class VideoProcessingWorkflow:
    """
    Full video processing pipeline.

    Each step is an Activity with its own timeout, heartbeat timeout, and
    retry policy. If this worker crashes mid-pipeline, Temporal replays
    the event history and resumes from the last completed activity.

    The course rebuild runs as a child workflow so it gets its own durable
    execution context after this workflow completes and frees its memory.
    """

    @workflow.run
    async def run(self, inp: VideoProcessingInput) -> dict:

        # ── Step 1: Download video from Vimeo ────────────────────────────
        dl: DownloadOutput = await workflow.execute_activity(
            download_video,
            DownloadInput(
                job_id=inp.job_id,
                vimeo_video_id=inp.vimeo_video_id,
                video_url=inp.video_url,
                video_id=inp.video_id,
                media_root=inp.media_root,
            ),
            start_to_close_timeout=timedelta(minutes=60),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=_network_retry,
        )

        # ── Step 2: Extract audio + transcribe ────────────────────────────
        tx: TranscribeOutput = await workflow.execute_activity(
            extract_and_transcribe,
            TranscribeInput(
                job_id=inp.job_id,
                video_file=dl.video_file,
                media_root=inp.media_root,
            ),
            start_to_close_timeout=timedelta(minutes=90),
            heartbeat_timeout=timedelta(minutes=10),
            retry_policy=_network_retry,
        )

        # ── Step 3: Create FAISS vectorstore from transcript ─────────────
        embed: EmbedOutput = await workflow.execute_activity(
            create_embeddings,
            EmbedInput(
                job_id=inp.job_id,
                video_id=inp.video_id,
                course_id=inp.course_id,
                video_title=inp.video_title,
                transcript=tx.transcript,
                media_root=inp.media_root,
            ),
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=_network_retry,
        )

        # ── Step 4: Mark job complete and update video status ─────────────
        await workflow.execute_activity(
            mark_job_complete,
            MarkCompleteInput(
                job_id=inp.job_id,
                video_id=inp.video_id,
                course_id=inp.course_id,
                chunk_count=embed.chunk_count,
                segment_count=tx.segment_count,
                vectorstore_path=embed.vectorstore_abs_path,
                video_file=dl.video_file,
            ),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=_cleanup_retry,
        )

        # ── Step 5: Clean up .mp4 and .wav files ──────────────────────────
        await workflow.execute_activity(
            cleanup_media_files,
            CleanupInput(
                video_file=dl.video_file,
                audio_path=tx.audio_path,
            ),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=_cleanup_retry,
        )

        # ── Step 6: Rebuild course vectorstore (child workflow) ───────────
        # Run as a child workflow so this workflow can finish and release
        # memory before the FAISS merge begins.
        await workflow.execute_child_workflow(
            CourseRebuildWorkflow.run,
            RebuildCourseInput(course_id=inp.course_id),
            id=f'course-rebuild-{inp.course_id}',
            task_queue='video-processing',
            execution_timeout=timedelta(minutes=40),
        )

        return {
            'video_id': inp.video_id,
            'chunk_count': embed.chunk_count,
            'transcript_segments': tx.segment_count,
            'status': 'completed',
        }


@workflow.defn
class CourseRebuildWorkflow:
    """
    Rebuild course-level FAISS vectorstore by merging all per-video indexes.
    Runs as a standalone workflow so it always starts with a clean memory slate.
    """

    @workflow.run
    async def run(self, inp: RebuildCourseInput) -> str:
        return await workflow.execute_activity(
            rebuild_course_vectorstore,
            inp,
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(seconds=30),
            ),
        )
