"""
Management command: migrate_sm_vectorstores

Migrate study material vectorstores from the old layout:
    study_materials_vectorstore/{sm_id}_{stem}.vectorstore/      (per-file)
    study_materials_vectorstore/{sm_id}_{name}.vectorstore/      (merged)

To the new layout:
    study_materials_vectorstore/individual_vectorstores/{sm_id}_{stem}_vectorstore/   (per-file)
    study_materials_vectorstore/complete_vectorstores/{sm_id}_{name}_vectorstore/     (merged)

Usage:
    python manage.py migrate_sm_vectorstores --dry-run   # preview
    python manage.py migrate_sm_vectorstores             # execute
"""

import os
import re
import json
import shutil
import logging
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Migrate study material vectorstores to individual/complete layout'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Preview changes without moving any files',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        media_root = str(settings.MEDIA_ROOT)

        manifest = {
            'schema_version': 1,
            'migration_started_at': datetime.now().isoformat(),
            'migration_completed_at': None,
            'dry_run': dry_run,
            'per_file_vs': {},
            'merged_vs': {},
        }

        if dry_run:
            self.stdout.write(self.style.WARNING('=== DRY RUN — no files will be moved ===\n'))

        from apps.core.models.study_material import StudyMaterial
        from apps.core.models.study_material_file import StudyMaterialFile

        # ─────────────────────────────────────────────────────────────────────
        # Phase 1: Migrate per-file vectorstores (StudyMaterialFile)
        # ─────────────────────────────────────────────────────────────────────
        self.stdout.write('\nPhase 1: Migrating per-file vectorstores...')

        smf_records = StudyMaterialFile.objects.exclude(vectorstore_path='')

        for smf in smf_records:
            old_rel = smf.vectorstore_path
            old_abs = os.path.join(media_root, old_rel)

            if not os.path.isdir(old_abs):
                self.stdout.write(
                    self.style.WARNING(f'  [SKIP]  smf#{smf.id} ({smf.original_name}): path not found on disk')
                )
                manifest['per_file_vs'][str(smf.id)] = {
                    'study_material_file_id': smf.id,
                    'original_name': smf.original_name,
                    'old_relative_path': old_rel,
                    'status': 'skipped_missing',
                }
                continue

            # Compute new path: study_materials_vectorstore/individual_vectorstores/{sm_id}_{stem}_vectorstore
            # Old pattern: study_materials_vectorstore/{sm_id}_{stem}.vectorstore
            parts = old_rel.split('/')
            old_folder = parts[-1]
            stem, _ = os.path.splitext(old_folder)
            new_folder = stem + '_vectorstore'
            new_rel = os.path.join('study_materials_vectorstore', 'individual_vectorstores', new_folder)
            new_abs = os.path.join(media_root, new_rel)

            entry_key = str(smf.id)
            action = self._move_or_skip(
                dry_run, old_abs, new_abs, new_rel,
                f'  smf#{smf.id} ({smf.original_name})',
            )
            if not dry_run and action == 'moved':
                smf.vectorstore_path = new_rel
                smf.save(update_fields=['vectorstore_path'])

            manifest['per_file_vs'][entry_key] = {
                'study_material_file_id': smf.id,
                'original_name': smf.original_name,
                'old_relative_path': old_rel,
                'new_relative_path': new_rel if action in ('moved', 'dedup') else old_rel,
                'status': action,
                'db_updated': not dry_run and action in ('moved', 'dedup'),
            }

        # ─────────────────────────────────────────────────────────────────────
        # Phase 2: Migrate merged SM vectorstores (StudyMaterial.vectorstore_location)
        # ─────────────────────────────────────────────────────────────────────
        self.stdout.write('\nPhase 2: Migrating merged study material vectorstores...')

        sm_records = StudyMaterial.objects.exclude(vectorstore_location='')

        for sm in sm_records:
            old_rel = sm.vectorstore_location
            old_abs = os.path.join(media_root, old_rel)

            if not os.path.isdir(old_abs):
                self.stdout.write(
                    self.style.WARNING(f'  [SKIP]  sm#{sm.id} ({sm.name}): path not found on disk')
                )
                manifest['merged_vs'][str(sm.id)] = {
                    'study_material_id': sm.id,
                    'name': sm.name,
                    'old_relative_path': old_rel,
                    'status': 'skipped_missing',
                }
                continue

            # Old dir names like: {sm_id}_{slug}.vectorstore -> include sm name
            # New: study_materials_vectorstore/complete_vectorstores/{sm_id}_{name}_vectorstore
            new_folder = f'{sm.id}_{self._slugify(sm.name)}_vectorstore'
            new_rel = os.path.join('study_materials_vectorstore', 'complete_vectorstores', new_folder)
            new_abs = os.path.join(media_root, new_rel)

            entry_key = str(sm.id)
            action = self._move_or_skip(
                dry_run, old_abs, new_abs, new_rel,
                f'  sm#{sm.id} ({sm.name})',
            )
            if not dry_run and action == 'moved':
                sm.vectorstore_location = new_rel
                sm.save(update_fields=['vectorstore_location'])

            manifest['merged_vs'][entry_key] = {
                'study_material_id': sm.id,
                'name': sm.name,
                'old_relative_path': old_rel,
                'new_relative_path': new_rel if action in ('moved', 'dedup') else old_rel,
                'status': action,
                'db_updated': not dry_run and action in ('moved', 'dedup'),
            }

        # ─────────────────────────────────────────────────────────────────────
        # Save manifest
        # ─────────────────────────────────────────────────────────────────────
        manifest['migration_completed_at'] = datetime.now().isoformat()
        manifest_path = os.path.join(media_root, 'sm_migration_manifest.json')

        if not dry_run:
            with open(manifest_path, 'w') as f:
                json.dump(manifest, f, indent=2, default=str)
            self.stdout.write(f'\nManifest saved: {manifest_path}')

        # Summary
        moved = sum(1 for v in manifest['per_file_vs'].values() if v['status'] == 'moved') + \
                sum(1 for v in manifest['merged_vs'].values() if v['status'] == 'moved')
        dedup = sum(1 for v in manifest['per_file_vs'].values() if v['status'] == 'dedup') + \
                sum(1 for v in manifest['merged_vs'].values() if v['status'] == 'dedup')
        skipped = sum(1 for v in manifest['per_file_vs'].values() if v['status'] == 'skipped_missing') + \
                  sum(1 for v in manifest['merged_vs'].values() if v['status'] == 'skipped_missing')

        self.stdout.write(
            self.style.SUCCESS(
                f'\n{"✅" if not dry_run else ""} Migration {"preview" if dry_run else "complete"}: '
                f'{moved} moved, {dedup} deduped, {skipped} skipped (missing on disk)'
            )
        )

    # ── helpers ──

    @staticmethod
    def _slugify(text: str) -> str:
        return re.sub(r'[^a-zA-Z0-9]+', '_', text).strip('_')

    def _move_or_skip(self, dry_run, old_abs, new_abs, new_rel, label):
        if os.path.isdir(new_abs) and os.path.exists(os.path.join(new_abs, 'index.faiss')):
            self.stdout.write(
                f'  [DEDUP] {label} → {new_rel} (already exists, DB pointer only)'
            )
            if not dry_run:
                shutil.rmtree(old_abs, ignore_errors=True)
            return 'dedup'

        self.stdout.write(f'  [MOVE]  {label} → {new_rel}')
        if not dry_run:
            os.makedirs(os.path.dirname(new_abs), exist_ok=True)
            shutil.move(old_abs, new_abs)
        return 'moved'
