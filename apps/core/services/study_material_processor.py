"""
StudyMaterialProcessor — 4-phase per-file vectorstore pipeline.

Phase 1 — DISCOVERY: extract zip recursively, create StudyMaterialFile records.
Phase 2 — PER-FILE:  convert each file → text → individual FAISS vectorstore.
Phase 3 — MERGE:     merge all per-file VSs into one full SM vectorstore.
Phase 4 — CLEANUP:   delete zip + raw extracted files, keep text/ and vectorstores.
"""

import os
import re
import shutil
import logging
from dataclasses import dataclass
from typing import List
from django.conf import settings
from django.utils import timezone
from django.db import transaction
from django.db.models import F

from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings

from apps.core.services.zip_extractor import ZipExtractor, FileEntry
from apps.core.services.file_converter import FileConverter
from apps.core.services.embedder import Embedder, EmbedResult

logger = logging.getLogger(__name__)

# ── Segmentation constant ─────────────────────────────────────────────────────
# Files producing more chunks than this are embedded in segments and merged.
# At BATCH_SIZE~500-1000 and BATCH_DELAY=1s, each segment takes ~2-3 min.
MAX_CHUNKS_PER_SEGMENT = 50_000


@dataclass
class ProcessResult:
    success: bool
    study_material_id: int = 0
    files_count: int = 0
    processed_files: int = 0
    vectorstore_location: str = ''
    error: str = ''


class StudyMaterialProcessor:
    """
    Orchestrates the study material pipeline.
    Resumable — Phase 2 skips files already status='completed'.
    """

    def __init__(self, openai_api_key: str = ''):
        self.openai_api_key = openai_api_key or settings.OPENAI_API_KEY
        self.extractor = ZipExtractor()
        self.converter = FileConverter()
        self.embedder = Embedder(openai_api_key=self.openai_api_key)

    # ─────────────────────────────────────────────────────────────────────────
    # Public entry point
    # ─────────────────────────────────────────────────────────────────────────

    def run(self, study_material) -> ProcessResult:
        from apps.core.models.study_material import StudyMaterial
        from apps.core.models.study_material_file import StudyMaterialFile

        sm = StudyMaterial.objects.get(pk=study_material.pk)

        try:
            # Only run discovery if we haven't already listed the files
            if sm.status == StudyMaterial.STATUS_PENDING:
                logger.info(f'[Processor] Phase 1: Discovery for SM "{sm.name}" (id={sm.id})')
                sm = self._phase1_discovery(sm)

            logger.info(f'[Processor] Phase 2: Per-file processing for SM "{sm.name}"')
            sm = self._phase2_process_files(sm)

            logger.info(f'[Processor] Phase 3: Merging file vectorstores for SM "{sm.name}"')
            vs_relative = self._phase3_merge(sm)

            sm.status = StudyMaterial.STATUS_COMPLETED
            sm.vectorstore_location = vs_relative
            sm.error_log = ''
            sm.save(update_fields=['status', 'vectorstore_location', 'error_log'])

            logger.info(f'[Processor] Phase 4: Cleanup for SM "{sm.name}"')
            self._phase4_cleanup(sm)

            logger.info(
                f'[Processor] DONE SM "{sm.name}": '
                f'{sm.processed_files}/{sm.files_count} files, VS at {vs_relative}'
            )

            return ProcessResult(
                success=True,
                study_material_id=sm.id,
                files_count=sm.files_count,
                processed_files=sm.processed_files,
                vectorstore_location=vs_relative,
            )

        except Exception as exc:
            logger.exception(f'[Processor] FAILED SM "{sm.name}": {exc}')
            try:
                sm.status = StudyMaterial.STATUS_FAILED
                sm.error_log = str(exc)
                sm.save(update_fields=['status', 'error_log'])
            except Exception:
                pass
            return ProcessResult(
                success=False,
                study_material_id=sm.id,
                error=str(exc),
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 1 — Discovery
    # ─────────────────────────────────────────────────────────────────────────

    def _phase1_discovery(self, sm):
        from apps.core.models.study_material import StudyMaterial
        from apps.core.models.study_material_file import StudyMaterialFile

        zip_path = sm.file_path
        if not os.path.exists(zip_path):
            raise FileNotFoundError(f'Zip not found: {zip_path}')

        raw_dir = os.path.join(str(settings.MEDIA_ROOT), 'study_materials', self._slug(sm.name))
        os.makedirs(raw_dir, exist_ok=True)

        logger.info(f'[ZipExtractor] Extracting: {os.path.basename(zip_path)} → {raw_dir}')
        entries: List[FileEntry] = self.extractor.extract(zip_path, raw_dir)
        logger.info(f'[ZipExtractor] Discovered {len(entries)} files')

        if not entries:
            raise ValueError('No extractable files found in zip')

        # Bulk-create StudyMaterialFile records
        smf_objects = [
            StudyMaterialFile(
                study_material=sm,
                original_name=os.path.basename(e.relative_path),
                relative_path=e.relative_path,
                file_type=e.ext,
                file_size=e.size,
                status=StudyMaterialFile.STATUS_PENDING,
            )
            for e in entries
        ]
        with transaction.atomic():
            StudyMaterialFile.objects.bulk_create(smf_objects)
            sm.files_count = len(entries)
            sm.processed_files = 0
            sm.status = StudyMaterial.STATUS_PROCESSING
            sm.save(update_fields=['files_count', 'processed_files', 'status'])

        logger.info(
            f'[Processor] Discovered {len(entries)} files → '
            f'{len(entries)} StudyMaterialFile records created'
        )
        return sm

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 2 — Per-file processing
    # ─────────────────────────────────────────────────────────────────────────

    def _phase2_process_files(self, sm):
        from apps.core.models.study_material_file import StudyMaterialFile

        pending_files = sm.files.filter(
            status__in=[StudyMaterialFile.STATUS_PENDING, StudyMaterialFile.STATUS_FAILED]
        ).order_by('created_at')

        total = sm.files_count
        raw_dir = os.path.join(str(settings.MEDIA_ROOT), 'study_materials', self._slug(sm.name))
        text_dir = os.path.join(raw_dir, 'text')
        os.makedirs(text_dir, exist_ok=True)

        for smf in pending_files:
            i = sm.processed_files + 1
            smf.status = StudyMaterialFile.STATUS_PROCESSING
            smf.save(update_fields=['status'])

            try:
                # Build abs path for the extracted file
                abs_path = os.path.join(raw_dir, smf.relative_path)

                # Create a FileEntry compatible object for the converter
                entry = FileEntry(
                    abs_path=abs_path,
                    relative_path=smf.relative_path,
                    ext=smf.file_type,
                    size=smf.file_size,
                )

                conv = self.converter.convert(entry)

                if conv.skipped:
                    smf.status = StudyMaterialFile.STATUS_SKIPPED
                    smf.processed_at = timezone.now()
                    smf.save(update_fields=['status', 'processed_at'])
                    logger.info(f'[Processor] [{i}/{total}] ⊘ {smf.original_name} (skipped)')
                    continue

                if not conv.success:
                    raise ValueError(conv.error)

                # Save text file (flat, deduplicated)
                stem = os.path.splitext(smf.original_name)[0]
                txt_filename = f'{stem}.txt'
                txt_path = os.path.join(text_dir, txt_filename)
                counter = 1
                while os.path.exists(txt_path):
                    txt_filename = f'{stem}_{counter}.txt'
                    txt_path = os.path.join(text_dir, txt_filename)
                    counter += 1

                with open(txt_path, 'w', encoding='utf-8') as f:
                    f.write(conv.text)

                txt_relative = os.path.join(
                    'study_materials', self._slug(sm.name), 'text', txt_filename
                )

                # Build per-file vectorstore
                vs_folder = f'{sm.id}_{stem}_vectorstore'
                vs_path = os.path.join(
                    str(settings.MEDIA_ROOT), 'study_materials_vectorstore', 'individual_vectorstores', vs_folder
                )
                vs_relative = os.path.join('study_materials_vectorstore', 'individual_vectorstores', vs_folder)

                embed_result = self._embed_with_segmentation(
                    text=conv.text,
                    save_path=vs_path,
                    metadata={
                        'source': smf.original_name,
                        'relative_path': smf.relative_path,
                        'file_type': smf.file_type,
                        'study_material_id': sm.id,
                        'study_material_name': sm.name,
                    },
                )

                # Update StudyMaterialFile record
                smf.text_path = txt_relative
                smf.vectorstore_path = vs_relative
                smf.chunk_count = embed_result.chunk_count
                smf.status = StudyMaterialFile.STATUS_COMPLETED
                smf.processed_at = timezone.now()
                smf.error = ''
                smf.save(update_fields=[
                    'text_path', 'vectorstore_path', 'chunk_count',
                    'status', 'processed_at', 'error',
                ])

                # Atomically increment processed_files counter on SM
                from apps.core.models.study_material import StudyMaterial
                StudyMaterial.objects.filter(pk=sm.pk).update(processed_files=F('processed_files') + 1)
                sm.refresh_from_db(fields=['processed_files'])

                logger.info(
                    f'[Processor] [{i}/{total}] ✓ {smf.original_name} '
                    f'→ {embed_result.chunk_count} chunks'
                )

            except Exception as exc:
                from celery.exceptions import SoftTimeLimitExceeded
                if isinstance(exc, SoftTimeLimitExceeded):
                    # Re-raise to let the celery task handle checkpointing and graceful exit
                    raise
                
                smf.status = StudyMaterialFile.STATUS_FAILED
                smf.error = str(exc)
                smf.processed_at = timezone.now()
                smf.save(update_fields=['status', 'error', 'processed_at'])
                logger.warning(
                    f'[Processor] [{i}/{total}] ✗ {smf.original_name}: {exc}'
                )
                # Continue — do not abort the pipeline for a single file failure

        return sm

    # ─────────────────────────────────────────────────────────────────────────
    # Segmented embedding for large files
    # ─────────────────────────────────────────────────────────────────────────

    def _embed_with_segmentation(
        self, text: str, save_path: str, metadata: dict,
    ) -> EmbedResult:
        """
        Embed text with automatic segmentation for very large files.
        If chunks > MAX_CHUNKS_PER_SEGMENT, split into segments,
        embed each separately, then merge into one per-file vectorstore.
        """
        # Pre-chunk to check size
        chunks = self.embedder.text_splitter.split_text(text)
        total_chunks = len(chunks)

        if total_chunks <= MAX_CHUNKS_PER_SEGMENT:
            # Small enough — single-shot
            result = self.embedder.create_vectorstore(text, save_path, metadata)
            if not result.success:
                raise ValueError(f'Embedding failed: {result.error}')
            return result

        # ── Large file: segment and merge ──
        logger.info(
            f'[Processor] Large file: {total_chunks:,} chunks → '
            f'splitting into segments of {MAX_CHUNKS_PER_SEGMENT:,}'
        )

        embeddings = OpenAIEmbeddings(
            openai_api_key=self.openai_api_key,
            model='text-embedding-3-small',
        )
        merged_vs = None
        segment_count = 0
        total_embedded = 0

        for seg_start in range(0, total_chunks, MAX_CHUNKS_PER_SEGMENT):
            segment_count += 1
            seg_chunks = chunks[seg_start: seg_start + MAX_CHUNKS_PER_SEGMENT]
            seg_text = '\n\n'.join(seg_chunks)

            seg_path = f'{save_path}.seg{segment_count}'

            result = self.embedder.create_vectorstore(
                transcript_text=seg_text,
                save_path=seg_path,
                metadata=metadata,
            )

            if not result.success:
                logger.warning(
                    f'[Processor] Segment {segment_count} failed: {result.error}'
                )
                continue

            total_embedded += result.chunk_count

            # Load and merge
            try:
                vs = FAISS.load_local(
                    seg_path, embeddings,
                    allow_dangerous_deserialization=True,
                )
                if merged_vs is None:
                    merged_vs = vs
                else:
                    merged_vs.merge_from(vs)
            except Exception as exc:
                logger.warning(
                    f'[Processor] Could not load segment {segment_count}: {exc}'
                )
            finally:
                # Clean up segment vectorstore
                if os.path.exists(seg_path):
                    shutil.rmtree(seg_path)

            logger.info(
                f'[Processor] Segment {segment_count}: '
                f'{len(seg_chunks):,} chunks '
                f'({total_embedded:,}/{total_chunks:,} total)'
            )

        if merged_vs is None:
            raise ValueError('All segments failed to embed')

        # Save merged vectorstore
        os.makedirs(save_path, exist_ok=True)
        merged_vs.save_local(save_path)

        logger.info(
            f'[Processor] Merged {segment_count} segments → '
            f'{total_embedded:,} chunks at {save_path}'
        )

        return EmbedResult(
            success=True,
            vectorstore_path=save_path,
            chunk_count=total_embedded,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 3 — Merge per-file VSs into full SM vectorstore
    # ─────────────────────────────────────────────────────────────────────────

    def _phase3_merge(self, sm) -> str:
        from apps.core.models.study_material_file import StudyMaterialFile

        completed_files = sm.files.filter(
            status=StudyMaterialFile.STATUS_COMPLETED
        ).exclude(vectorstore_path='')

        if not completed_files.exists():
            raise ValueError('No successfully processed files to merge')

        embeddings = OpenAIEmbeddings(openai_api_key=self.openai_api_key)
        merged_vs = None

        for smf in completed_files:
            vs_abs = os.path.join(str(settings.MEDIA_ROOT), smf.vectorstore_path)
            if not os.path.exists(vs_abs):
                logger.warning(f'[Processor] Per-file VS missing, skipping: {vs_abs}')
                continue
            try:
                vs = FAISS.load_local(vs_abs, embeddings, allow_dangerous_deserialization=True)
                if merged_vs is None:
                    merged_vs = vs
                else:
                    merged_vs.merge_from(vs)
            except Exception as exc:
                logger.warning(f'[Processor] Could not load VS for {smf.original_name}: {exc}')

        if merged_vs is None:
            raise ValueError('All per-file vectorstores failed to load — cannot produce merged VS')

        vs_folder = f'{sm.id}_{self._slug(sm.name)}_vectorstore'
        vs_path = os.path.join(str(settings.MEDIA_ROOT), 'study_materials_vectorstore', 'complete_vectorstores', vs_folder)
        vs_relative = os.path.join('study_materials_vectorstore', 'complete_vectorstores', vs_folder)

        # Atomic save: write to temp dir then rename
        tmp_path = vs_path + '.tmp'
        os.makedirs(tmp_path, exist_ok=True)
        merged_vs.save_local(tmp_path)
        if os.path.exists(vs_path):
            shutil.rmtree(vs_path)
        os.rename(tmp_path, vs_path)

        n = completed_files.count()
        logger.info(
            f'[Processor] Phase 3: Merged {n} file vectorstores → {vs_path}'
        )
        return vs_relative

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 4 — Cleanup
    # ─────────────────────────────────────────────────────────────────────────

    def _phase4_cleanup(self, sm):
        from apps.core.models.study_material_file import StudyMaterialFile

        raw_dir = os.path.join(str(settings.MEDIA_ROOT), 'study_materials', self._slug(sm.name))
        text_dir = os.path.join(raw_dir, 'text')

        # Delete original zip
        if sm.file_path and os.path.exists(sm.file_path):
            os.remove(sm.file_path)
            logger.debug(f'[Processor] Deleted zip: {sm.file_path}')

        # Delete all raw extracted files (keep text/)
        for smf in sm.files.all():
            raw_path = os.path.join(raw_dir, smf.relative_path)
            if os.path.exists(raw_path):
                try:
                    os.remove(raw_path)
                except OSError:
                    pass

        # Remove empty subdirs in raw_dir (but preserve text/)
        for root, dirs, files in os.walk(raw_dir, topdown=False):
            if root == text_dir or root.startswith(text_dir + os.sep):
                continue
            if not files and not dirs:
                try:
                    os.rmdir(root)
                except OSError:
                    pass

        logger.info(f'[Processor] Phase 4: Cleanup complete for SM "{sm.name}"')

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _slug(text: str) -> str:
        return re.sub(r'[^a-zA-Z0-9]+', '_', text).strip('_')
