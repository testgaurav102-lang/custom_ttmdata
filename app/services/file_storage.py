"""
Local file-storage bookkeeping service.

Maintains a JSON index of uploaded files so that metadata (name, size, MIME
type, path) can be retrieved by ``file_id`` without hitting S3.

PDF generation has been moved to ``app.services.pdf_service``.
"""

import json
import logging
import os
import time
import uuid
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

INDEX_FILE = os.path.join(settings.upload_dir, ".file_index.json")


class FileRecord:
    """Metadata record for a single uploaded file."""

    def __init__(
        self,
        file_id: str,
        file_name: str,
        size_in_bytes: int,
        mime_type: str,
        extension: str,
        file_path: str,
        label: Optional[str] = None,
        uploaded_at: Optional[float] = None,
    ) -> None:
        self.file_id = file_id
        self.file_name = file_name
        self.size_in_bytes = size_in_bytes
        self.mime_type = mime_type
        self.extension = extension
        self.file_path = file_path
        self.label = label or extension
        self.uploaded_at = uploaded_at or time.time()

    def to_dict(self) -> dict:
        return {
            "file_id": self.file_id,
            "file_name": self.file_name,
            "size_in_bytes": self.size_in_bytes,
            "mime_type": self.mime_type,
            "extension": self.extension,
            "file_path": self.file_path,
            "label": self.label,
            "uploaded_at": self.uploaded_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FileRecord":
        return cls(
            file_id=data["file_id"],
            file_name=data["file_name"],
            size_in_bytes=data["size_in_bytes"],
            mime_type=data["mime_type"],
            extension=data["extension"],
            file_path=data["file_path"],
            label=data.get("label"),
            uploaded_at=data.get("uploaded_at"),
        )


class FileStorageService:
    """In-process registry of uploaded files backed by a JSON file on disk.

    The index is stored at ``uploads/.file_index.json`` (configurable via
    ``settings.upload_dir``).  Records whose on-disk path no longer exists are
    silently dropped when the index is loaded at startup.
    """

    def __init__(self) -> None:
        self._files: dict[str, FileRecord] = {}
        self._load_index()

    # ------------------------------------------------------------------
    # Index persistence
    # ------------------------------------------------------------------

    def _load_index(self) -> None:
        path = INDEX_FILE
        if not os.path.exists(path):
            return
        try:
            with open(path) as f:
                data = json.load(f)
            loaded = 0
            for item in data:
                record = FileRecord.from_dict(item)
                if os.path.exists(record.file_path):
                    self._files[record.file_id] = record
                    loaded += 1
            logger.debug("Loaded %d file records from index.", loaded)
        except Exception as exc:
            logger.warning("Failed to load file index, starting empty: %s", exc)
            self._files = {}

    def _save_index(self) -> None:
        os.makedirs(os.path.dirname(INDEX_FILE), exist_ok=True)
        data = [r.to_dict() for r in self._files.values()]
        with open(INDEX_FILE, "w") as f:
            json.dump(data, f, indent=2)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def store(
        self,
        file_name: str,
        size_in_bytes: int,
        mime_type: str,
        extension: str,
        file_path: str,
        label: Optional[str] = None,
    ) -> FileRecord:
        """Register a new file and persist the updated index."""
        file_id = str(uuid.uuid4())
        record = FileRecord(
            file_id=file_id,
            file_name=file_name,
            size_in_bytes=size_in_bytes,
            mime_type=mime_type,
            extension=extension,
            file_path=file_path,
            label=label,
        )
        self._files[file_id] = record
        self._save_index()
        logger.debug("Stored file record: %s (%s)", file_name, file_id)
        return record

    def get(self, file_id: str) -> Optional[FileRecord]:
        return self._files.get(file_id)

    def delete(self, file_id: str) -> bool:
        """Remove the record and the underlying file.  Returns True if found."""
        record = self._files.pop(file_id, None)
        if record is None:
            return False
        try:
            if os.path.exists(record.file_path):
                os.remove(record.file_path)
        except OSError as exc:
            logger.warning("Could not remove file %s: %s", record.file_path, exc)
        self._save_index()
        logger.debug("Deleted file record: %s", file_id)
        return True

    def delete_many(self, file_ids: list[str]) -> dict[str, bool]:
        """Bulk delete.  Returns a mapping of ``file_id → was_found``."""
        return {fid: self.delete(fid) for fid in file_ids}

    def generate_url(self, file_id: str, expiry_seconds: int = 3600) -> Optional[dict]:
        """Generate a local download URL dict for a stored file."""
        record = self.get(file_id)
        if record is None:
            return None
        return {
            "url": f"{settings.base_url}/files/{file_id}/download",
            "expiresIn": expiry_seconds,
            "mimeType": record.mime_type,
            "fileName": record.file_name,
            "sizeInBytes": record.size_in_bytes,
        }


# Module-level singleton
file_storage = FileStorageService()
