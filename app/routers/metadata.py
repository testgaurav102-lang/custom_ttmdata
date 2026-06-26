from fastapi import APIRouter

from app.config import settings
from app.models.metadata import MetadataResponse, ModelMode, FileTypeSupport

router = APIRouter()


@router.get("/metadata", response_model=MetadataResponse)
async def get_metadata():
    models = [
        ModelMode(**m) for m in settings.supported_models
    ]
    file_types = [
        FileTypeSupport(
            extension="csv",
            mimeType="text/csv",
            maxSizeInBytes=settings.max_file_size_mb * 1024 * 1024,
        ),
        FileTypeSupport(
            extension="xls",
            mimeType="application/vnd.ms-excel",
            maxSizeInBytes=settings.max_file_size_mb * 1024 * 1024,
        ),
        FileTypeSupport(
            extension="xlsx",
            mimeType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            maxSizeInBytes=settings.max_file_size_mb * 1024 * 1024,
        ),
    ]
    return MetadataResponse(
        modelsSupported=models,
        defaultModel=settings.default_model,
        supportsFileUpload=True,
        fileTypes=file_types,
        maxFileUploadCount=settings.max_file_upload_count,
        supportsStreaming=True,
    )
