"""
Management command: migrate_vectorstores

One-time migration to move existing vectorstores from the old layout:
    media/course_{id}/vectorstore/video_{db_id}/
    media/course_{id}/vectorstore/course_complete/

To the new global layout:
    media/video_vectorstores/{vimeo_video_id}/
    media/course_vectorstores/{course_id}_{slug}/

Usage:
    python manage.py migrate_vectorstores --dry-run   # preview
    python manage.py migrate_vectorstores             # execute
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
    help = 'Migrate vectorstores from per-course to global layout'

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
            'videos': {},
            'courses': {},
        }

        if dry_run:
            self.stdout.write(self.style.WARNING('=== DRY RUN — no files will be moved ===\n'))

        # ------------------------------------------------------------------
        # Phase 1: Scan for video vectorstores
        # ------------------------------------------------------------------
        self.stdout.write('Phase 1: Scanning for video vectorstores...')

        from apps.core.models import Video

        # Find all course_* directories
        course_dirs = [
            d for d in os.listdir(media_root)
            if os.path.isdir(os.path.join(media_root, d))
            and re.match(r'^course_\d+$', d)
        ]

        video_work_list = []

        for course_dir in sorted(course_dirs):
            vs_dir = os.path.join(media_root, course_dir, 'vectorstore')
            if not os.path.isdir(vs_dir):
                continue

            for entry in os.listdir(vs_dir):
                # Match video_* directories (e.g. video_21, video_42)
                match = re.match(r'^video_(\d+)$', entry)
                if not match:
                    continue

                db_video_id = int(match.group(1))
                old_abs = os.path.join(vs_dir, entry)

                if not os.path.isdir(old_abs):
                    continue

                # Look up vimeo_video_id from DB
                try:
                    video = Video.objects.get(id=db_video_id)
                    vimeo_id = video.vimeo_video_id
                except Video.DoesNotExist:
                    self.stdout.write(
                        self.style.WARNING(f'  DB video {db_video_id} not found — skipping')
                    )
                    manifest['videos'][str(db_video_id)] = {
                        'db_video_id': db_video_id,
                        'old_path': old_abs,
                        'status': 'skipped_db_missing',
                    }
                    continue

                if not vimeo_id:
                    self.stdout.write(
                        self.style.WARNING(
                            f'  Video {db_video_id} has no vimeo_video_id — skipping'
                        )
                    )
                    manifest['videos'][str(db_video_id)] = {
                        'db_video_id': db_video_id,
                        'old_path': old_abs,
                        'status': 'skipped_no_vimeo_id',
                    }
                    continue

                video_work_list.append({
                    'db_video_id': db_video_id,
                    'vimeo_id': vimeo_id,
                    'old_abs': old_abs,
                    'old_rel': os.path.relpath(old_abs, media_root),
                    'new_rel': os.path.join('video_vectorstores', vimeo_id),
                    'video_obj': video,
                })

        self.stdout.write(f'  Found {len(video_work_list)} video vectorstores to migrate\n')

        # ------------------------------------------------------------------
        # Phase 2: Move video vectorstores
        # ------------------------------------------------------------------
        self.stdout.write('Phase 2: Migrating video vectorstores...')

        new_vs_dir = os.path.join(media_root, 'video_vectorstores')
        if not dry_run:
            os.makedirs(new_vs_dir, exist_ok=True)

        for item in sorted(video_work_list, key=lambda x: x['db_video_id']):
            new_abs = os.path.join(media_root, item['new_rel'])
            entry_key = str(item['db_video_id'])

            if os.path.isdir(new_abs) and os.path.exists(os.path.join(new_abs, 'index.faiss')):
                # Already exists — just update DB pointer (dedup)
                self.stdout.write(
                    f"  [DEDUP] video_{item['db_video_id']} → {item['new_rel']} "
                    f"(already exists, DB pointer only)"
                )
                if not dry_run:
                    video = item['video_obj']
                    video.vectorstore_path = item['new_rel']
                    video.save(update_fields=['vectorstore_path'])
                    # Remove old directory since destination already has the data
                    shutil.rmtree(item['old_abs'], ignore_errors=True)

                manifest['videos'][entry_key] = {
                    'db_video_id': item['db_video_id'],
                    'vimeo_video_id': item['vimeo_id'],
                    'old_relative_path': item['old_rel'],
                    'new_relative_path': item['new_rel'],
                    'status': 'dedup_pointer',
                    'db_updated': not dry_run,
                }
            else:
                # Move to new location
                self.stdout.write(
                    f"  [MOVE]  video_{item['db_video_id']} → {item['new_rel']}"
                )
                if not dry_run:
                    os.makedirs(os.path.dirname(new_abs), exist_ok=True)
                    shutil.move(item['old_abs'], new_abs)

                    video = item['video_obj']
                    video.vectorstore_path = item['new_rel']
                    video.save(update_fields=['vectorstore_path'])

                manifest['videos'][entry_key] = {
                    'db_video_id': item['db_video_id'],
                    'vimeo_video_id': item['vimeo_id'],
                    'old_relative_path': item['old_rel'],
                    'new_relative_path': item['new_rel'],
                    'status': 'moved',
                    'db_updated': not dry_run,
                }

        # ------------------------------------------------------------------
        # Phase 3: Move course vectorstores
        # ------------------------------------------------------------------
        self.stdout.write('\nPhase 3: Migrating course vectorstores...')

        from apps.core.models import Course
        from apps.core.services.aggregator import CourseAggregator

        courses = Course.objects.filter(vectorstore_created=True)

        for course in courses:
            # Old path pattern
            old_abs = os.path.join(
                media_root, f'course_{course.id}', 'vectorstore', 'course_complete',
            )
            new_rel = CourseAggregator.get_course_vs_relative(course)
            new_abs = os.path.join(media_root, new_rel)

            entry_key = str(course.id)

            if not os.path.isdir(old_abs):
                self.stdout.write(
                    self.style.WARNING(
                        f'  Course {course.id} ({course.title}): '
                        f'old path not found — skipping'
                    )
                )
                manifest['courses'][entry_key] = {
                    'course_id': course.id,
                    'course_title': course.title,
                    'status': 'skipped_missing',
                }
                continue

            self.stdout.write(
                f'  [MOVE] course_{course.id}/course_complete → {new_rel}'
            )

            if not dry_run:
                os.makedirs(os.path.dirname(new_abs), exist_ok=True)
                if os.path.exists(new_abs):
                    shutil.rmtree(new_abs)
                shutil.move(old_abs, new_abs)

                course.vectorstore_path = new_rel
                course.save(update_fields=['vectorstore_path'])

            manifest['courses'][entry_key] = {
                'course_id': course.id,
                'course_title': course.title,
                'old_relative_path': os.path.relpath(old_abs, media_root),
                'new_relative_path': new_rel,
                'status': 'moved',
                'db_updated': not dry_run,
            }

        # ------------------------------------------------------------------
        # Phase 4: Cleanup empty old directories
        # ------------------------------------------------------------------
        self.stdout.write('\nPhase 4: Cleaning up empty directories...')

        for course_dir in sorted(course_dirs):
            vs_dir = os.path.join(media_root, course_dir, 'vectorstore')
            course_abs = os.path.join(media_root, course_dir)

            if not os.path.isdir(vs_dir):
                continue

            # Check if vectorstore dir is now empty
            remaining = os.listdir(vs_dir) if os.path.isdir(vs_dir) else []
            if not remaining:
                self.stdout.write(f'  [DELETE] {course_dir}/vectorstore/ (empty)')
                if not dry_run:
                    shutil.rmtree(vs_dir, ignore_errors=True)
                    # Also remove parent if empty
                    if os.path.isdir(course_abs) and not os.listdir(course_abs):
                        shutil.rmtree(course_abs, ignore_errors=True)
                        self.stdout.write(f'  [DELETE] {course_dir}/ (empty)')
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f'  [KEEP]  {course_dir}/vectorstore/ '
                        f'({len(remaining)} items remaining)'
                    )
                )

        # ------------------------------------------------------------------
        # Save manifest
        # ------------------------------------------------------------------
        manifest['migration_completed_at'] = datetime.now().isoformat()
        manifest_path = os.path.join(media_root, 'migration_manifest.json')

        if not dry_run:
            with open(manifest_path, 'w') as f:
                json.dump(manifest, f, indent=2, default=str)
            self.stdout.write(f'\nManifest saved: {manifest_path}')

        # Summary
        video_moved = sum(
            1 for v in manifest['videos'].values() if v['status'] == 'moved'
        )
        video_dedup = sum(
            1 for v in manifest['videos'].values() if v['status'] == 'dedup_pointer'
        )
        course_moved = sum(
            1 for c in manifest['courses'].values() if c['status'] == 'moved'
        )

        self.stdout.write(
            self.style.SUCCESS(
                f'\n✅ Migration {"preview" if dry_run else "complete"}: '
                f'{video_moved} videos moved, {video_dedup} deduped, '
                f'{course_moved} courses moved'
            )
        )
