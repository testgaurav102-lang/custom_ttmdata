from pydantic import BaseModel
from typing import Optional
from enum import Enum


class ContentType(str, Enum):
    text = "text"
    json = "json"
    file = "file"
    fileCitation = "fileCitation"
    linkCitation = "linkCitation"
    activityText = "activityText"


class CitationLocation(BaseModel):
    id: int
    page: Optional[int] = None
    highlightText: Optional[str] = None


class FileCitationContent(BaseModel):
    ref: int
    fileId: str
    title: Optional[str] = None
    locations: list[CitationLocation] = []


class LinkCitationContent(BaseModel):
    ref: int
    url: str
    title: Optional[str] = None


class ContentItem(BaseModel):
    contentType: str
    content: dict | str | None = None


class Message(BaseModel):
    role: str
    contents: list[ContentItem]


class ChatCompletionRequest(BaseModel):
    chatId: str
    messageId: str
    model: str = "llama3.1"
    mode: str = "quick_search"
    messages: list[Message]
    files: list[dict] = []


class CompletionContentItem(BaseModel):
    contentType: str
    content: dict | str | None = None


class ChatCompletionResponse(BaseModel):
    completionId: str
    contents: list[ContentItem]
    inputTokens: int = 0
    outputTokens: int = 0


class StopResponse(BaseModel):
    completionId: str
    status: str = "stopped"
    message: str = "Chat completion successfully stopped"


class ErrorResponse(BaseModel):
    error_code: str
    error_message: str
