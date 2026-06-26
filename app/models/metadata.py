from pydantic import BaseModel


class ModelMode(BaseModel):
    modelName: str
    modes: list[str]
    defaultMode: str


class FileTypeSupport(BaseModel):
    extension: str
    mimeType: str
    maxSizeInBytes: int


class MetadataResponse(BaseModel):
    modelsSupported: list[ModelMode]
    defaultModel: str
    supportsFileUpload: bool = True
    fileTypes: list[FileTypeSupport]
    maxFileUploadCount: int = 1
    supportsStreaming: bool = True
