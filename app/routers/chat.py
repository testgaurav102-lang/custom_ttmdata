"""
Chat completion endpoints.

Routes:
  POST /chat/completions                  Start a streaming SSE analysis.
  POST /chat/completions/{id}/stop        Stop an in-progress completion.
"""

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import StreamingResponse

from app.models.chat import (
    ChatCompletionRequest,
    ErrorResponse,
    StopResponse,
)
from app.services.llm_service import llm_service

logger = logging.getLogger(__name__)
router = APIRouter()


def verify_auth(authorization: Optional[str] = Header(None)) -> str:
    """Validate the Bearer token from the Authorization header.

    Currently defined but not enforced on individual routes.  Attach as a
    dependency to routes when authentication is required.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header.")
    return authorization


@router.post("/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    """Start a new streaming chat completion and return an SSE response."""
    completion_id = uuid.uuid4().hex
    llm_service.register_completion(completion_id)
    logger.debug("Starting completion %s for chat %s.", completion_id, request.chatId)

    file_ids = [f.fileId for f in request.files]

    async def stream_response():
        async for chunk in llm_service.generate_streaming(
            messages=request.model_dump().get("messages", []),
            completion_id=completion_id,
            file_ids=file_ids,
        ):
            yield chunk

    return StreamingResponse(stream_response(), media_type="text/event-stream",headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    },)


@router.post("/chat/completions/{completion_id}/stop", response_model=StopResponse)
async def stop_completion(completion_id: str):
    """Stop an in-progress completion identified by *completion_id*."""
    result = llm_service.stop_completion(completion_id)
    if not result["found"]:
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error_code="COMPLETION_NOT_FOUND",
                error_message="The specified completion ID does not exist.",
            ).model_dump(),
        )
    logger.info("Completion %s stopped by client request.", completion_id)
    return StopResponse(
        completionId=completion_id,
        status="stopped",
        message="Chat completion successfully stopped",
    )
