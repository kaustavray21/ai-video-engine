import os
import zipfile
import logging
from dataclasses import dataclass
from typing import List

logger = logging.getLogger(__name__)


@dataclass
class FileEntry:
    abs_path: str
    relative_path: str
    ext: str
    size: int


class ZipExtractor:
    """
    Recursively extract a .zip archive.

    - Nested .zip members are extracted into a matching subdirectory,
      then recursed into. The nested .zip is deleted after extraction.
    - Path traversal attacks (../) are sanitised.
    - Returns a flat list of FileEntry for all extracted files.
    """

    def extract(self, zip_path: str, extract_dir: str) -> List[FileEntry]:
        os.makedirs(extract_dir, exist_ok=True)
        entries: List[FileEntry] = []
        self._extract_recursive(zip_path, extract_dir, entries, "")
        return entries

    def _extract_recursive(
        self,
        zip_path: str,
        extract_dir: str,
        entries: List[FileEntry],
        prefix: str,
    ):
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for member in zf.namelist():
                safe_relative = self._sanitise(member)
                if safe_relative is None:
                    continue

                full_relative = os.path.join(prefix, safe_relative) if prefix else safe_relative
                target_path = os.path.join(extract_dir, full_relative)

                if member.endswith('.zip'):
                    nested_dir = os.path.dirname(target_path)
                    os.makedirs(nested_dir, exist_ok=True)
                    with open(target_path, 'wb') as f:
                        f.write(zf.read(member))
                    inner_prefix = os.path.splitext(full_relative)[0]
                    self._extract_recursive(target_path, extract_dir, entries, inner_prefix)
                    os.remove(target_path)

                elif member.endswith('/'):
                    os.makedirs(target_path, exist_ok=True)

                else:
                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    with open(target_path, 'wb') as f:
                        f.write(zf.read(member))

                    entries.append(FileEntry(
                        abs_path=target_path,
                        relative_path=full_relative,
                        ext=os.path.splitext(safe_relative)[1].lower(),
                        size=os.path.getsize(target_path),
                    ))

    @staticmethod
    def _sanitise(path: str) -> str | None:
        parts = path.replace('\\', '/').split('/')
        clean = [p for p in parts if p not in ('', '.', '..')]
        if not clean:
            return None
        return '/'.join(clean)
