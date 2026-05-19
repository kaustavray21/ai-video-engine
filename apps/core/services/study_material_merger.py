import os
import re
import shutil
import tempfile
import logging
from dataclasses import dataclass
from typing import Optional

from django.conf import settings

from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings

logger = logging.getLogger(__name__)


@dataclass
class MergeResult:
    success: bool
    merged_path: str = ''
    merged_relative: str = ''
    error: str = ''


class StudyMaterialMerger:
    """
    Build or replace a merged vectorstore combining a course's existing
    video vectorstore with a study material's standalone vectorstore.

    The original course vectorstore is NEVER modified.
    """

    def __init__(self, openai_api_key: str = ''):
        self.openai_api_key = openai_api_key or settings.OPENAI_API_KEY
        self.embeddings = OpenAIEmbeddings(openai_api_key=self.openai_api_key)

    # ── Path helpers ──

    @staticmethod
    def _slugify(text: str) -> str:
        return re.sub(r'[^a-zA-Z0-9]+', '_', text).strip('_')

    @staticmethod
    def get_merged_vs_path(course, study_material) -> str:
        course_slug = StudyMaterialMerger._slugify(course.title)
        sm_slug = StudyMaterialMerger._slugify(study_material.name)
        folder_name = f'{course.id}_{course_slug}_{study_material.id}_{sm_slug}.vectorstore'
        return os.path.join(
            str(settings.MEDIA_ROOT),
            'course_vectorstores',
            f'{course.id}_{course_slug}',
            folder_name,
        )

    @staticmethod
    def get_merged_vs_relative(course, study_material) -> str:
        course_slug = StudyMaterialMerger._slugify(course.title)
        sm_slug = StudyMaterialMerger._slugify(study_material.name)
        folder_name = f'{course.id}_{course_slug}_{study_material.id}_{sm_slug}.vectorstore'
        return os.path.join(
            'course_vectorstores',
            f'{course.id}_{course_slug}',
            folder_name,
        )

    @staticmethod
    def get_course_vs_abs(course) -> str:
        path = course.vectorstore_path
        if not path:
            return ''
        if os.path.isabs(path):
            return path
        return os.path.join(str(settings.MEDIA_ROOT), path)

    # ── Build ──

    def build(self, course, study_material) -> MergeResult:
        """
        Load course vectorstore + SM vectorstore, merge into new index,
        save atomically to a new subfolder.
        """
        course_vs_path = self.get_course_vs_abs(course)
        if not course_vs_path or not os.path.exists(course_vs_path):
            return MergeResult(
                success=False,
                error=f'Course vectorstore not found: {course_vs_path}',
            )

        sm_vs_path = os.path.join(
            str(settings.MEDIA_ROOT), study_material.vectorstore_location,
        )
        if not os.path.exists(sm_vs_path):
            return MergeResult(
                success=False,
                error=f'Study material vectorstore not found: {sm_vs_path}',
            )

        try:
            course_vs = FAISS.load_local(
                course_vs_path, self.embeddings,
                allow_dangerous_deserialization=True,
            )
            sm_vs = FAISS.load_local(
                sm_vs_path, self.embeddings,
                allow_dangerous_deserialization=True,
            )

            course_vs.merge_from(sm_vs)

            final_path = self.get_merged_vs_path(course, study_material)
            relative_path = self.get_merged_vs_relative(course, study_material)
            parent_dir = os.path.dirname(final_path)
            os.makedirs(parent_dir, exist_ok=True)

            temp_path = tempfile.mkdtemp(dir=parent_dir, prefix='merged_vs_tmp_')
            try:
                course_vs.save_local(temp_path)
                if os.path.exists(final_path):
                    shutil.rmtree(final_path)
                os.rename(temp_path, final_path)
            except Exception:
                if os.path.exists(temp_path):
                    shutil.rmtree(temp_path, ignore_errors=True)
                raise

            logger.info(
                f'Merged vectorstore created for course "{course.title}" '
                f'+ SM "{study_material.name}": {relative_path}'
            )

            return MergeResult(
                success=True,
                merged_path=final_path,
                merged_relative=relative_path,
            )

        except Exception as e:
            logger.exception(f'Merged vectorstore build failed: {e}')
            return MergeResult(success=False, error=str(e))

    # ── Replace ──

    def replace(self, course, study_material) -> MergeResult:
        """Delete old merged folder and rebuild with new study material."""
        if course.merged_vectorstore_path:
            old_path = os.path.join(
                str(settings.MEDIA_ROOT), course.merged_vectorstore_path,
            )
            if os.path.exists(old_path):
                shutil.rmtree(old_path)
                logger.info(f'Deleted old merged vectorstore: {old_path}')

        return self.build(course, study_material)
