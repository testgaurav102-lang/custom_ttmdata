"""
File management endpoints.

Routes:
  POST   /files                   Upload a CSV / XLS / XLSX file.
  GET    /files/{file_id}/url     Get a presigned S3 download URL.
  DELETE /files                   Bulk-delete files from S3 by comma-separated IDs.
"""

import logging
import os
import uuid
from typing import Optional

from botocore.exceptions import ClientError
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pathlib import Path

from app.config import settings
from app.constants import DEFAULT_FILE_LABEL, MIME_TO_EXT, SUPPORTED_EXTENSIONS
from app.models.file import (
    FileErrorResponse,
    FileUploadResponse,
    SheetInfo,
)
from app.services.aws_service import BUCKET, s3_client
from app.services.data_loader import data_loader
from app.services.file_storage import file_storage

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


@router.post("/files", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    fileName: Optional[str] = Form(None),
    mimeType: Optional[str] = Form(None),
    extension: Optional[str] = Form(None),
):
    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=400,
            detail=FileErrorResponse(
                error_code="EMPTY_FILE",
                error_message="Empty file is not allowed.",
            ).model_dump(),
        )

    # Resolve file extension from explicit param, filename, or MIME type
    ext = ""
    if extension:
        ext = extension.lower()
    elif file.filename and "." in file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()
    elif mimeType:
        ext = MIME_TO_EXT.get(mimeType.lower(), "")
    elif file.content_type:
        ext = MIME_TO_EXT.get(file.content_type.lower(), "")

    mime = mimeType or file.content_type or "application/octet-stream"
    name = fileName or file.filename or f"file.{ext or 'csv'}"

    if not ext or ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=FileErrorResponse(
                error_code="UNSUPPORTED_FILE",
                error_message=f"Unsupported file type: '{ext or 'unknown'}'",
            ).model_dump(),
        )

    if len(content) > settings.max_file_size_mb * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=FileErrorResponse(
                error_code="FILE_SIZE_EXCEEDED",
                error_message="File size exceeds maximum allowed limit.",
            ).model_dump(),
        )

    file_id = str(uuid.uuid4())
    base_dir = Path("/tmp") / file_id
    original_dir = base_dir / "original"
    os.makedirs(original_dir, exist_ok=True)

    s3_key = f"{file_id}/original/{file.filename}"
    original_file_path = original_dir / file.filename

    try:
        with open(original_file_path, "wb") as f:
            f.write(content)

        s3_client.upload_file(str(original_file_path), BUCKET, s3_key)
        logger.info("Uploaded file to S3: %s", s3_key)

        sheets: list[SheetInfo] = []
        try:
            loaded_tables = data_loader.load_file(str(original_file_path), name, file_id)
            sheets = [
                SheetInfo(
                    sheetName=t["sheet_name"],
                    tableName=t["table_name"],
                    rowCount=t["row_count"],
                    columns=t["columns"],
                )
                for t in loaded_tables
            ]
        except Exception as exc:
            logger.warning("File uploaded to S3 but DuckDB load failed: %s", exc)

        return FileUploadResponse(
            fileId=file_id,
            fileName=name,
            sizeInBytes=len(content),
            label=DEFAULT_FILE_LABEL,
            sheets=sheets,
        )

    except Exception as exc:
        logger.error("Upload failed for file_id=%s: %s", file_id, exc)
        if original_file_path.exists():
            try:
                os.remove(original_file_path)
            except OSError:
                pass
        raise HTTPException(
            status_code=400,
            detail=FileErrorResponse(
                error_code="COULD_NOT_PROCESS",
                error_message="File could not be processed.",
            ).model_dump(),
        )


# ---------------------------------------------------------------------------
# Presigned URL
# ---------------------------------------------------------------------------


@router.get("/files/{file_id}/url")
async def get_file_url(file_id: str):
    """Return a presigned S3 download URL for *file_id*."""
    prefix = f"{file_id}/original/"

    try:
        response = s3_client.list_objects_v2(Bucket=BUCKET, Prefix=prefix)
        objects = response.get("Contents", [])

        if not objects:
            return {
                "error_code": "FILE_NOT_FOUND",
                "error_message": "The specified file ID does not exist.",
            }

        s3_key = objects[0]["Key"]
        file_name = s3_key.split("/")[-1]

        try:
            head = s3_client.head_object(Bucket=BUCKET, Key=s3_key)
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("403", "AccessDenied"):
                return {"error_code": "ACCESS_DENIED", "error_message": "No permission to access this file."}
            if code in ("404", "NoSuchKey"):
                return {"error_code": "FILE_NOT_FOUND", "error_message": "The specified file ID does not exist."}
            logger.error("S3 head_object error for %s: %s", file_id, exc)
            return {"error_code": "INTERNAL_ERROR", "error_message": "Failed to fetch file metadata."}

        mime_type = head.get("ContentType", "application/octet-stream")
        size_in_bytes = head.get("ContentLength", 0)
        expires_in = settings.file_url_expiry_seconds

        try:
            signed_url = s3_client.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": BUCKET, "Key": s3_key},
                ExpiresIn=expires_in,
            )
        except Exception as exc:
            msg = str(exc).lower()
            if "expired" in msg or "timeout" in msg:
                return {"error_code": "URL_EXPIRED", "error_message": "File access URL has expired."}
            logger.error("Failed to generate presigned URL for %s: %s", file_id, exc)
            return {"error_code": "INTERNAL_ERROR", "error_message": "Failed to generate file URL."}

        return {
            "url": signed_url,
            "expiresIn": expires_in,
            "mimeType": mime_type,
            "fileName": file_name,
            "sizeInBytes": size_in_bytes,
        }

    except Exception as exc:
        logger.error("Unhandled error for file_id=%s: %s", file_id, exc)
        return {
            "error_code": "INTERNAL_ERROR",
            "error_message": str(exc),
        }


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


@router.delete("/files")
async def delete_files(fileIds: str):
    """Bulk-delete files from S3.  *fileIds* is a comma-separated string."""
    file_ids = [fid.strip() for fid in fileIds.split(",") if fid.strip()]

    try:
        for file_id in file_ids:
            prefix = f"{file_id}/"
            response = s3_client.list_objects_v2(Bucket=BUCKET, Prefix=prefix)
            contents = response.get("Contents")

            if not contents:
                logger.debug("No S3 objects found for file_id=%s, skipping.", file_id)
                continue

            objects_to_delete = [{"Key": obj["Key"]} for obj in contents]
            logger.debug("Deleting %d S3 objects for file_id=%s.", len(objects_to_delete), file_id)

            delete_response = s3_client.delete_objects(
                Bucket=BUCKET,
                Delete={"Objects": objects_to_delete, "Quiet": False},
            )
            logger.info(
                "Deleted %d objects for file_id=%s.",
                len(delete_response.get("Deleted", [])),
                file_id,
            )

            data_loader.drop_file_tables(file_id)

        return {"message": "File deleted successfully."}

    except Exception as exc:
        logger.error("Unhandled delete error for fileIds=%s: %s", fileIds, exc)
        return {
            "error_code": "DELETE_FAILED",
            "error_message": "Failed to delete files due to internal error.",
        }
