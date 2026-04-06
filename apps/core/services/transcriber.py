"""
Transcriber service — audio extraction + OpenAI Whisper API transcription.

Extracted from: api/live_video_processor.py (_extract_audio, _generate_transcript)
               course_creator_tools/audio_transcription_utils.py
"""

import os
import logging
import subprocess
from dataclasses import dataclass
from typing import Optional

from openai import OpenAI

logger = logging.getLogger(__name__)


@dataclass
class TranscriptResult:
    success: bool
    transcript: str = ''
    transcript_file: str = ''
    segment_count: int = 0
    error: str = ''


class Transcriber:
    """Extract audio from video files and transcribe using OpenAI Whisper API."""

    def __init__(self, openai_api_key: str):
        self.client = OpenAI(api_key=openai_api_key)

    def extract_audio(self, video_path: str) -> Optional[str]:
        """
        Extract audio from video using ffmpeg.

        Args:
            video_path: Absolute path to the video file.

        Returns:
            Path to the extracted .wav file, or None on failure.
        """
        if not os.path.exists(video_path):
            logger.error(f'Video file not found: {video_path}')
            return None

        audio_path = os.path.splitext(video_path)[0] + '.wav'

        cmd = [
            'ffmpeg', '-y',
            '-i', video_path,
            '-threads', '1',          # limit cpu usage
            '-vn',                    # no video
            '-acodec', 'pcm_s16le',   # 16-bit PCM
            '-ar', '16000',           # 16 kHz (optimal for Whisper)
            '-ac', '1',               # mono
            audio_path,
        ]

        try:
            logger.info(f'Extracting audio: {video_path} → {audio_path}')
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=600
            )
            if result.returncode != 0:
                logger.error(f'ffmpeg error: {result.stderr[:500]}')
                return None

            if not os.path.exists(audio_path):
                logger.error('ffmpeg produced no output file')
                return None

            logger.info(f'Audio extracted: {audio_path}')
            return audio_path

        except subprocess.TimeoutExpired:
            logger.error('ffmpeg timed out after 600s')
            return None
        except FileNotFoundError:
            logger.error('ffmpeg not found. Install ffmpeg and ensure it is on PATH.')
            return None
        except Exception as e:
            logger.exception(f'Audio extraction failed: {e}')
            return None

    def transcribe(self, audio_path: str) -> TranscriptResult:
        """
        Transcribe audio using the OpenAI Whisper API.

        The audio file is split into ≤25 MB chunks if needed (Whisper API limit).

        Args:
            audio_path: Path to .wav audio file.

        Returns:
            TranscriptResult with full transcript text.
        """
        if not os.path.exists(audio_path):
            return TranscriptResult(success=False, error=f'Audio file not found: {audio_path}')

        try:
            file_size = os.path.getsize(audio_path)
            logger.info(
                f'Transcribing {audio_path} ({file_size / (1024*1024):.1f} MB)'
            )

            # Whisper API accepts files up to 25 MB.
            # For larger files, we split into chunks.
            if file_size > 24 * 1024 * 1024:
                return self._transcribe_large(audio_path)

            with open(audio_path, 'rb') as audio_file:
                response = self.client.audio.transcriptions.create(
                    model='whisper-1',
                    file=audio_file,
                    response_format='verbose_json',
                )

            transcript_text = response.text
            segments = getattr(response, 'segments', []) or []

            # Save transcript to disk
            transcript_path = os.path.splitext(audio_path)[0] + '.txt'
            with open(transcript_path, 'w', encoding='utf-8') as f:
                f.write(transcript_text)

            logger.info(
                f'Transcription complete: {len(transcript_text)} chars, '
                f'{len(segments)} segments'
            )

            return TranscriptResult(
                success=True,
                transcript=transcript_text,
                transcript_file=transcript_path,
                segment_count=len(segments),
            )

        except Exception as e:
            logger.exception(f'Transcription failed: {e}')
            return TranscriptResult(success=False, error=str(e))

    def _transcribe_large(self, audio_path: str) -> TranscriptResult:
        """
        Split large audio into ≤24 MB chunks, transcribe each, and concatenate.
        Uses ffmpeg to split on 10-minute boundaries.
        """
        import math

        logger.info('Audio > 24 MB — splitting into chunks')

        # Get duration
        probe_cmd = [
            'ffprobe', '-v', 'quiet',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            audio_path,
        ]
        try:
            probe = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=30)
            total_duration = float(probe.stdout.strip())
        except Exception:
            total_duration = 3600  # fallback 1h

        chunk_duration = 600  # 10 minutes
        num_chunks = math.ceil(total_duration / chunk_duration)
        base = os.path.splitext(audio_path)[0]

        all_text = []
        total_segments = 0

        for i in range(num_chunks):
            start = i * chunk_duration
            chunk_path = f'{base}_chunk{i}.wav'

            split_cmd = [
                'ffmpeg', '-y',
                '-i', audio_path,
                '-threads', '1',
                '-ss', str(start),
                '-t', str(chunk_duration),
                '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1',
                chunk_path,
            ]
            subprocess.run(split_cmd, capture_output=True, timeout=120)

            if not os.path.exists(chunk_path):
                continue

            try:
                with open(chunk_path, 'rb') as f:
                    resp = self.client.audio.transcriptions.create(
                        model='whisper-1', file=f, response_format='verbose_json',
                    )
                all_text.append(resp.text)
                total_segments += len(getattr(resp, 'segments', []) or [])
            except Exception as e:
                logger.warning(f'Chunk {i} transcription failed: {e}')
            finally:
                # Clean up chunk
                if os.path.exists(chunk_path):
                    os.remove(chunk_path)

        full_transcript = ' '.join(all_text)

        transcript_path = os.path.splitext(audio_path)[0] + '.txt'
        with open(transcript_path, 'w', encoding='utf-8') as f:
            f.write(full_transcript)

        return TranscriptResult(
            success=bool(full_transcript),
            transcript=full_transcript,
            transcript_file=transcript_path,
            segment_count=total_segments,
            error='' if full_transcript else 'No transcript produced from chunks',
        )
