"""
Vimeo video downloader service.

Extracted from: yt_transcribe/vimeo_ytdlp_downloader.py (VimeoDownloader, lines 46-316)
Uses Vimeo REST API with access token — no yt-dlp dependency.
"""

import os
import re
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)


@dataclass
class DownloadResult:
    success: bool
    video_file: str = ''
    vimeo_video_id: str = ''
    title: str = ''
    duration: int = 0
    width: int = 0
    height: int = 0
    fps: float = 0
    filesize: int = 0
    uploader: str = ''
    description: str = ''
    metadata: dict = None
    error: str = ''

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class VimeoDownloader:
    """
    Download Vimeo videos using the Vimeo REST API with an access token.
    No username/password or yt-dlp required.
    """

    VIMEO_API_BASE = 'https://api.vimeo.com/videos'

    def __init__(self, vimeo_token: str, output_dir: str = 'media/live_videos'):
        self.vimeo_token = vimeo_token
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def extract_video_id(url: str) -> Optional[str]:
        """Extract numeric video ID from common Vimeo URL formats."""
        patterns = [
            r'vimeo\.com/(\d+)',
            r'player\.vimeo\.com/video/(\d+)',
            r'/videos/(\d+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    def download(self, video_id: str) -> DownloadResult:
        """
        Download a Vimeo video by its numeric ID.

        Returns a DownloadResult with file path and metadata.
        """
        if not self.vimeo_token:
            return DownloadResult(success=False, error='No Vimeo API token configured')

        logger.info(f'Fetching metadata for video {video_id} via Vimeo API')

        # 1. Fetch metadata
        api_url = f'{self.VIMEO_API_BASE}/{video_id}'
        headers = {'Authorization': f'Bearer {self.vimeo_token}'}

        try:
            resp = requests.get(api_url, headers=headers, timeout=30)
        except requests.RequestException as exc:
            logger.exception(f'Network error contacting Vimeo API: {exc}')
            return DownloadResult(success=False, error=f'Network error: {exc}')

        if resp.status_code != 200:
            logger.error(f'Vimeo API returned HTTP {resp.status_code}')
            return DownloadResult(
                success=False,
                error=f'Vimeo API error (HTTP {resp.status_code})'
            )

        data = resp.json()

        # 2. Pick best download link
        downloads = data.get('download')
        if not downloads:
            return DownloadResult(
                success=False,
                error='No download links available. Check Vimeo permissions and token scopes.'
            )

        sorted_downloads = sorted(
            downloads,
            key=lambda d: d.get('height', 0) or 0,
            reverse=True,
        )
        chosen = sorted_downloads[0]
        download_url = chosen.get('link')

        if not download_url:
            return DownloadResult(success=False, error='Download link is empty')

        # 3. Download file
        title = data.get('name', video_id)
        safe_title = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')[:80]
        output_file = self.output_dir / f'live_{video_id}_{safe_title}.mp4'

        logger.info(f'Downloading to {output_file}')

        try:
            with requests.get(download_url, stream=True, timeout=600) as dl:
                dl.raise_for_status()
                total = int(dl.headers.get('content-length', 0))
                downloaded = 0
                with open(output_file, 'wb') as f:
                    for chunk in dl.iter_content(chunk_size=8192 * 16):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0 and downloaded % (5 * 1024 * 1024) < 8192 * 16:
                            pct = (downloaded / total) * 100
                            logger.info(f'Download progress: {pct:.1f}%')
        except requests.RequestException as exc:
            logger.exception(f'Download failed: {exc}')
            return DownloadResult(success=False, error=f'Download failed: {exc}')

        logger.info(f'Download completed: {output_file}')

        # 4. Build result
        result = DownloadResult(
            success=True,
            video_file=str(output_file),
            vimeo_video_id=video_id,
            title=title,
            duration=data.get('duration', 0),
            width=chosen.get('width', 0),
            height=chosen.get('height', 0),
            fps=chosen.get('fps', 0),
            filesize=os.path.getsize(output_file),
            uploader=data.get('user', {}).get('name', ''),
            description=data.get('description', ''),
            metadata={
                'view_count': data.get('stats', {}).get('plays', 0),
                'tags': [t['name'] for t in data.get('tags', [])],
                'release_time': data.get('release_time', ''),
            },
        )

        # Save metadata sidecar
        metadata_path = self.output_dir / f'live_{video_id}_metadata.json'
        with open(metadata_path, 'w') as f:
            json.dump(result.__dict__, f, indent=2, default=str)

        return result

    def get_info(self, video_id: str) -> Optional[Dict[str, Any]]:
        """Fetch video metadata without downloading."""
        if not self.vimeo_token:
            return None
        headers = {'Authorization': f'Bearer {self.vimeo_token}'}
        try:
            resp = requests.get(
                f'{self.VIMEO_API_BASE}/{video_id}',
                headers=headers, timeout=30
            )
            if resp.status_code == 200:
                return resp.json()
        except requests.RequestException:
            pass
        return None
