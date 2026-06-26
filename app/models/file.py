from pydantic import BaseModel
from typing import Optional


class FileInfo(BaseModel):
    fileId: str
    fileName: str
    sizeInBytes: int
    label: Optional[str] = None
    source: Optional[str] = None


class FileContent(BaseModel):
    fileId: str
    fileName: str
    sizeInBytes: int
    label: Optional[str] = None


class FileUploadResponse(BaseModel):
    fileId: str
    fileName: str
    sizeInBytes: int
    label: str


class FileUrlResponse(BaseModel):
    url: str
    expiresIn: int
    mimeType: str
    fileName: str
    sizeInBytes: int


class FileDeleteResponse(BaseModel):
    status: str = "success"
    deleted: list[str]
    not_found: list[str]


class FileErrorResponse(BaseModel):
    error_code: str
    error_message: str
