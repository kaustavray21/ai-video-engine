"""
Vimeo Transcript Service — fetch caption tracks (VTT) directly from the Vimeo API.

Used as the "fast path" in the video processing pipeline:
  If Vimeo already has captions → grab text → skip download/audio/whisper → embed.

Adapted from: architecture refactoring plan/vimeo_transcript_service.py
"""

import os
import logging
from typing import Dict, Any, List

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class VimeoTranscriptService:
    """
    Downloads and parses Vimeo caption tracks (VTT) for a given video.

    Usage:
        service = VimeoTranscriptService()
        result = service.fetch_transcript('1022483822')
        if result['success']:
            print(result['transcript_text'])  # plain text for embeddings
            print(result['transcript_path'])  # saved .txt file path
    """

    VIMEO_API_BASE = "https://api.vimeo.com"

    def __init__(self, vimeo_token: str = None):
        self.vimeo_token = vimeo_token or getattr(settings, 'VIMEO_TOKEN', None)
        if not self.vimeo_token:
            logger.warning("VIMEO_TOKEN not configured. Vimeo transcript fetch will fail.")

        self.output_dir = os.path.join(str(settings.MEDIA_ROOT), 'live_videos')
        os.makedirs(self.output_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_transcript(self, vimeo_video_id: str) -> Dict[str, Any]:
        """
        Attempt to fetch a Vimeo caption track for the given video.

        Returns:
            {
                'success': bool,
                'transcript_text': str,      # plain text (for embeddings)
                'transcript_path': str,      # absolute path to saved .txt
                'language': str,             # e.g. 'en', 'en-x-autogen'
                'line_count': int,
                'error': str | None,
            }
        """
        try:
            logger.info(f"[VimeoTranscript] Fetching text tracks for video {vimeo_video_id}...")
            tracks = self._get_text_tracks(vimeo_video_id)

            if not tracks:
                return self._fail("No caption tracks found for this video")

            # Pick best English track
            track = self._pick_best_track(tracks)
            language = track.get('language', 'unknown')
            logger.info(f"[VimeoTranscript] Selected track: language={language}")

            # Download VTT content
            vtt_link = track.get('link')
            if not vtt_link:
                return self._fail("Caption track has no download link")

            vtt_content = self._download_vtt(vtt_link)
            if not vtt_content:
                return self._fail("Downloaded VTT content is empty")

            # Parse VTT
            parsed_cues = self._parse_vtt(vtt_content)
            if not parsed_cues:
                return self._fail("No cues parsed from VTT content")

            # Build plain text (for embeddings) — just the spoken text joined
            transcript_text = ' '.join(cue['text'] for cue in parsed_cues)

            # Build timestamped text (for audit/storage)
            timestamped_text = self._build_timestamped_text(parsed_cues)

            # Save to disk
            txt_path = os.path.join(
                self.output_dir,
                f"{vimeo_video_id}_vimeo_transcript.txt"
            )
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(timestamped_text)

            logger.info(
                f"[VimeoTranscript] ✅ Saved {len(parsed_cues)} cues to {txt_path}"
            )

            return {
                'success': True,
                'transcript_text': transcript_text,
                'transcript_path': txt_path,
                'language': language,
                'line_count': len(parsed_cues),
                'error': None,
            }

        except requests.exceptions.HTTPError as e:
            logger.error(f"[VimeoTranscript] HTTP error: {e}")
            return self._fail(f"Vimeo API HTTP error: {e}")
        except Exception as e:
            logger.error(f"[VimeoTranscript] Unexpected error: {e}", exc_info=True)
            return self._fail(str(e))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_text_tracks(self, video_id: str) -> List[dict]:
        """Call Vimeo API to list text tracks for a video."""
        url = f"{self.VIMEO_API_BASE}/videos/{video_id}/texttracks"
        headers = {"Authorization": f"Bearer {self.vimeo_token}"}

        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get('data', [])

    @staticmethod
    def _pick_best_track(tracks: List[dict]) -> dict:
        """
        Priority: en (exact) > en-* (autogen, en-US, etc.) > first available.
        """
        for track in tracks:
            if track.get('language') == 'en':
                return track
        for track in tracks:
            lang = track.get('language', '')
            if lang.startswith('en'):
                return track
        return tracks[0]

    @staticmethod
    def _download_vtt(url: str) -> str:
        """Download raw VTT content from a URL."""
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        return resp.text

    @staticmethod
    def _parse_vtt(content: str) -> List[dict]:
        """
        Parse WebVTT content into a list of {time, text} dicts.
        Strips WEBVTT header, numeric sequence IDs, and empty lines.
        """
        lines = content.split('\n')
        result = []
        timestamp = ''

        for line in lines:
            line = line.strip()
            if '-->' in line:
                timestamp = line
            elif line and not line.isnumeric() and 'WEBVTT' not in line:
                result.append({
                    'time': timestamp,
                    'text': line,
                })

        return result

    @staticmethod
    def _build_timestamped_text(cues: List[dict]) -> str:
        """Build timestamped text file content for audit/display."""
        lines = []
        for cue in cues:
            lines.append(f"{cue['time']}")
            lines.append(cue['text'])
            lines.append('')  # blank line separator
        return '\n'.join(lines)

    @staticmethod
    def _fail(message: str) -> Dict[str, Any]:
        return {
            'success': False,
            'transcript_text': '',
            'transcript_path': '',
            'language': '',
            'line_count': 0,
            'error': message,
        }
