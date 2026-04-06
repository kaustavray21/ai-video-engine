"""
Course aggregator — merge per-video FAISS indexes into a course-level index.

Extracted from: api/live_course_vectorstore_builder.py (CourseVectorstoreBuilder, 1-291)
"""

import os
import shutil
import tempfile
import logging
from dataclasses import dataclass
from typing import Optional

from django.conf import settings
from django.utils import timezone
from django.db.models import Max

from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings

logger = logging.getLogger(__name__)


@dataclass
class AggregationResult:
    status: str            # 'success' | 'skipped' | 'error'
    reason: str = ''
    videos_merged: int = 0
    videos_skipped: int = 0
    vectorstore_path: str = ''


class CourseAggregator:
    """
    Builds and maintains course-level FAISS vectorstores by merging
    per-video indexes via FAISS.merge_from().
    """

    def __init__(self, openai_api_key: str = ''):
        self.openai_api_key = openai_api_key or settings.OPENAI_API_KEY

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    @staticmethod
    def get_course_vs_path(course) -> str:
        """Absolute path for the course-level vectorstore."""
        return os.path.join(
            str(settings.MEDIA_ROOT),
            f'course_{course.id}',
            'vectorstore',
            'course_complete',
        )

    @staticmethod
    def get_course_vs_relative(course) -> str:
        """Relative path (to MEDIA_ROOT)."""
        return os.path.join(
            f'course_{course.id}',
            'vectorstore',
            'course_complete',
        )

    @staticmethod
    def _resolve_video_vs_path(video) -> str:
        """Resolve absolute path for a video's vectorstore."""
        path = video.vectorstore_path
        if not path:
            return ''
        if os.path.isabs(path):
            return path
        return os.path.join(str(settings.MEDIA_ROOT), path)

    # ------------------------------------------------------------------
    # Staleness check
    # ------------------------------------------------------------------

    def is_stale(self, course) -> bool:
        """True if the course index should be rebuilt."""
        if not course.vectorstore_created:
            return True

        latest_completed = course.videos.filter(
            vectorstore_created=True,
        ).aggregate(
            latest=Max('processing_jobs__completed_at'),
        )['latest']

        if latest_completed and course.vectorstore_updated_at:
            return latest_completed > course.vectorstore_updated_at

        return True  # rebuild when uncertain

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def rebuild_if_stale(self, course) -> AggregationResult:
        """Rebuild only if stale."""
        if not self.is_stale(course):
            return AggregationResult(status='skipped', reason='up_to_date')
        return self.force_rebuild(course)

    def force_rebuild(self, course) -> AggregationResult:
        """
        Force rebuild: load each per-video FAISS → merge → atomic save.
        """
        embeddings = OpenAIEmbeddings(openai_api_key=self.openai_api_key)

        videos_with_vs = course.videos.filter(
            vectorstore_created=True, is_active=True,
        ).exclude(vectorstore_path='')

        video_count = videos_with_vs.count()
        if video_count == 0:
            return AggregationResult(
                status='skipped', reason='no_processed_videos',
            )

        logger.info(f'Rebuilding course vectorstore for "{course.title}" '
                     f'({video_count} videos)')

        merged = None
        loaded = 0
        skipped = 0

        for video in videos_with_vs:
            vs_path = self._resolve_video_vs_path(video)
            if not vs_path or not os.path.exists(vs_path):
                logger.warning(f'Vectorstore missing for video {video.id}: {vs_path}')
                skipped += 1
                continue

            try:
                video_vs = FAISS.load_local(
                    vs_path, embeddings,
                    allow_dangerous_deserialization=True,
                )
                if merged is None:
                    merged = video_vs
                else:
                    merged.merge_from(video_vs)
                loaded += 1
                logger.info(f'  Merged video "{video.title}" ({loaded}/{video_count})')
            except Exception as e:
                logger.error(f'  Failed to load vectorstore for video {video.id}: {e}')
                skipped += 1

        if merged is None:
            return AggregationResult(status='error', reason='no_vectorstores_loaded')

        # Atomic save: temp dir → rename
        final_path = self.get_course_vs_path(course)
        relative_path = self.get_course_vs_relative(course)

        try:
            parent_dir = os.path.dirname(final_path)
            os.makedirs(parent_dir, exist_ok=True)

            temp_path = tempfile.mkdtemp(dir=parent_dir, prefix='course_vs_tmp_')
            merged.save_local(temp_path)

            if os.path.exists(final_path):
                shutil.rmtree(final_path)
            os.rename(temp_path, final_path)
        except Exception as e:
            if 'temp_path' in locals() and os.path.exists(temp_path):
                shutil.rmtree(temp_path, ignore_errors=True)
            return AggregationResult(status='error', reason=f'save_failed: {e}')

        # Update course model
        course.vectorstore_path = relative_path
        course.vectorstore_created = True
        course.vectorstore_updated_at = timezone.now()
        course.vectorstore_version = course.content_version
        course.save(update_fields=[
            'vectorstore_path', 'vectorstore_created', 'vectorstore_updated_at',
            'vectorstore_version',
        ])

        logger.info(
            f'Course vectorstore rebuilt: "{course.title}" — '
            f'{loaded} merged, {skipped} skipped'
        )

        return AggregationResult(
            status='success',
            videos_merged=loaded,
            videos_skipped=skipped,
            vectorstore_path=final_path,
        )
