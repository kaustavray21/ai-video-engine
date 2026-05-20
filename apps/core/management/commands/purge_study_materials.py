"""
Management command: purge_study_materials

Completely removes ALL study material data from the database and disk:

Database:
  - Deletes every StudyMaterialFile record
  - Deletes every StudyMaterial record
  - Removes study_material / merged_vectorstore_path / study_materials_history
    from every Course
  - Clears the M2M through table (attached_to_courses)

Disk (under MEDIA_ROOT):
  - Removes study_materials/  — extracted files & text conversions
  - Removes study_materials_vectorstore/  — individual & merged FAISS indexes
  - Removes course_vectorstores/  — merged course+SM FAISS indexes

Usage:
    python manage.py purge_study_materials
    python manage.py purge_study_materials --dry-run     # preview only
"""

import os
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Delete all study material data (DB records + files + vectorstores).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making any changes.',
        )

    def handle(self, *args, **options):
        dry = options['dry_run']

        self.stdout.write(self.style.WARNING(
            '\n══════════════════════════════════════════'
        ))
        self.stdout.write(self.style.WARNING(
            '  STUDY MATERIAL PURGE' + (' [DRY RUN]' if dry else '')
        ))
        self.stdout.write(self.style.WARNING(
            '══════════════════════════════════════════\n'
        ))

        media = Path(settings.MEDIA_ROOT)

        # ── Step 1: Count database records ──────────────────────────────────
        self.stdout.write('▶ Step 1 — Database records\n')

        from apps.core.models import StudyMaterial, StudyMaterialFile, Course

        sm_count = StudyMaterial.objects.count()
        smf_count = StudyMaterialFile.objects.count()

        courses_with_sm = Course.objects.exclude(
            study_material__isnull=True
        ).exclude(study_material={}).count()
        courses_with_merged = Course.objects.exclude(
            merged_vectorstore_path=''
        ).count()

        self.stdout.write(f'  StudyMaterial records:        {sm_count}')
        self.stdout.write(f'  StudyMaterialFile records:    {smf_count}')
        self.stdout.write(f'  Courses with study_material:  {courses_with_sm}')
        self.stdout.write(f'  Courses with merged VS path:  {courses_with_merged}')

        # ── Step 2: Count files on disk ─────────────────────────────────────
        self.stdout.write('\n▶ Step 2 — Disk (study material files)\n')

        study_materials_dir = media / 'study_materials'
        sm_vs_dir = media / 'study_materials_vectorstore'
        course_vs_dir = media / 'course_vectorstores'

        sm_files = sum(len(files) for _, _, files in os.walk(study_materials_dir)) if study_materials_dir.exists() else 0
        sm_dirs = len([d for d in study_materials_dir.iterdir() if d.is_dir()]) if study_materials_dir.exists() else 0

        sm_vs_files = sum(len(files) for _, _, files in os.walk(sm_vs_dir)) if sm_vs_dir.exists() else 0
        sm_vs_subdirs = len([d for d in sm_vs_dir.rglob('*') if d.is_dir()]) if sm_vs_dir.exists() else 0

        course_vs_files = sum(len(files) for _, _, files in os.walk(course_vs_dir)) if course_vs_dir.exists() else 0
        course_vs_subdirs = len([d for d in course_vs_dir.rglob('*') if d.is_dir()]) if course_vs_dir.exists() else 0

        self.stdout.write('  study_materials/')
        self.stdout.write(f'    directories: {sm_dirs}')
        self.stdout.write(f'    files:       {sm_files}')
        self.stdout.write('  study_materials_vectorstore/')
        self.stdout.write(f'    subdirs:     {sm_vs_subdirs}')
        self.stdout.write(f'    files:       {sm_vs_files}')
        self.stdout.write('  course_vectorstores/')
        self.stdout.write(f'    subdirs:     {course_vs_subdirs}')
        self.stdout.write(f'    files:       {course_vs_files}')

        # ── Confirm ─────────────────────────────────────────────────────────
        total = sm_count + smf_count
        if total == 0 and sm_files == 0 and sm_vs_files == 0 and course_vs_files == 0:
            self.stdout.write(self.style.NOTICE('\nNothing to clean — already empty.'))
            return

        self.stdout.write('')
        if not dry:
            confirm = input(
                f'Delete {total} DB record(s) and all study material files? [y/N] '
            )
            if confirm.lower() != 'y':
                self.stdout.write(self.style.WARNING('Aborted.'))
                return

        # ── Step 3: Clear Course references ─────────────────────────────────
        self.stdout.write('\n▶ Step 3 — Clearing Course references\n')

        if courses_with_sm or courses_with_merged:
            if not dry:
                Course.objects.update(
                    study_material=None,
                    merged_vectorstore_path='',
                    study_materials_history=[],
                )
                self.stdout.write(self.style.SUCCESS(
                    f'  ✓ Cleared study_material / merged_vectorstore_path / '
                    f'study_materials_history on {Course.objects.count()} course(s)'
                ))
            else:
                self.stdout.write('  [dry-run] Would clear SM fields on all courses.')
        else:
            self.stdout.write('  No course SM references to clear.')

        # ── Step 4: Disassociate M2M (attached_to_courses) ──────────────────
        self.stdout.write('\n▶ Step 4 — Clearing M2M through table (attached_to_courses)\n')

        if sm_count:
            if not dry:
                for sm in StudyMaterial.objects.iterator():
                    sm.attached_to_courses.clear()
                self.stdout.write(self.style.SUCCESS(
                    f'  ✓ Cleared attached_to_courses on {sm_count} study material(s)'
                ))
            else:
                self.stdout.write(f'  [dry-run] Would clear attached_to_courses on {sm_count} SM(s).')
        else:
            self.stdout.write('  No study materials to disassociate.')

        # ── Step 5: Delete StudyMaterialFile + StudyMaterial records ────────
        self.stdout.write('\n▶ Step 5 — Deleting database records\n')

        if smf_count:
            if not dry:
                StudyMaterialFile.objects.all().delete()
                self.stdout.write(self.style.SUCCESS(
                    f'  ✓ Deleted {smf_count} StudyMaterialFile record(s)'
                ))
            else:
                self.stdout.write(f'  [dry-run] Would delete {smf_count} StudyMaterialFile(s).')
        else:
            self.stdout.write('  No StudyMaterialFile records to delete.')

        if sm_count:
            if not dry:
                StudyMaterial.objects.all().delete()
                self.stdout.write(self.style.SUCCESS(
                    f'  ✓ Deleted {sm_count} StudyMaterial record(s)'
                ))
            else:
                self.stdout.write(f'  [dry-run] Would delete {sm_count} StudyMaterial(s).')
        else:
            self.stdout.write('  No StudyMaterial records to delete.')

        # ── Step 6: Remove disk directories ─────────────────────────────────
        self.stdout.write('\n▶ Step 6 — Removing study material directories on disk\n')

        dirs_to_remove = [
            ('study_materials/', study_materials_dir),
            ('study_materials_vectorstore/', sm_vs_dir),
            ('course_vectorstores/', course_vs_dir),
        ]

        for label, path in dirs_to_remove:
            if path.exists():
                if not dry:
                    shutil.rmtree(path)
                    self.stdout.write(self.style.SUCCESS(f'  ✓ Removed {label}'))
                else:
                    self.stdout.write(f'  [dry-run] Would remove {label}')
            else:
                self.stdout.write(f'  {label} — does not exist, skipped.')

        # ── Done ────────────────────────────────────────────────────────────
        self.stdout.write('')
        if dry:
            self.stdout.write(self.style.WARNING(
                'Dry run complete — no changes were made.'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                '✓ Purge complete. All study material data has been removed.'
            ))
        self.stdout.write('')
