"""
Custom management command: rundev

Builds the React dashboard and starts the Django dev server in one command.

Usage:
    python manage.py rundev
    python manage.py rundev --skip-build   # skip frontend build
    python manage.py rundev --port 8080    # custom port
"""

import os
import subprocess
import sys
from pathlib import Path

from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = 'Build the React dashboard and start the Django dev server'

    def add_arguments(self, parser):
        parser.add_argument(
            '--skip-build',
            action='store_true',
            help='Skip the frontend build step',
        )
        parser.add_argument(
            '--port',
            type=int,
            default=8000,
            help='Port for the Django dev server (default: 8000)',
        )

    def handle(self, *args, **options):
        dashboard_dir = Path(settings.BASE_DIR) / 'dashboard'
        skip_build = options['skip_build']
        port = options['port']

        # ── Step 1: Build the React dashboard ──
        if not skip_build:
            if not (dashboard_dir / 'package.json').exists():
                self.stderr.write(self.style.ERROR(
                    f'No package.json found in {dashboard_dir}'
                ))
                sys.exit(1)

            # Check if node_modules exists
            if not (dashboard_dir / 'node_modules').exists():
                self.stdout.write(self.style.WARNING('Installing npm dependencies...'))
                result = subprocess.run(
                    ['npm', 'install'],
                    cwd=str(dashboard_dir),
                    capture_output=False,
                )
                if result.returncode != 0:
                    self.stderr.write(self.style.ERROR('npm install failed'))
                    sys.exit(1)

            self.stdout.write(self.style.WARNING('Building React dashboard...'))
            result = subprocess.run(
                ['npm', 'run', 'build'],
                cwd=str(dashboard_dir),
                capture_output=False,
            )
            if result.returncode != 0:
                self.stderr.write(self.style.ERROR('Dashboard build failed'))
                sys.exit(1)

            self.stdout.write(self.style.SUCCESS(
                '✓ Dashboard built → dashboard/dist/'
            ))
        else:
            if (dashboard_dir / 'dist' / 'index.html').exists():
                self.stdout.write(self.style.SUCCESS(
                    '✓ Using existing dashboard build'
                ))
            else:
                self.stdout.write(self.style.WARNING(
                    '⚠ No dashboard build found. '
                    'Run without --skip-build to build it.'
                ))

        # ── Step 2: Start Django dev server ──
        self.stdout.write(self.style.SUCCESS(
            f'\n🚀 Starting Django on http://127.0.0.1:{port}/'
        ))
        self.stdout.write(self.style.SUCCESS(
            f'📊 Dashboard at http://127.0.0.1:{port}/dashboard/'
        ))
        self.stdout.write('')

        from django.core.management import call_command
        call_command('runserver', f'0.0.0.0:{port}')
