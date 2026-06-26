"""
AWS / S3 client initialisation.

The bucket name and credentials are read from ``app.config.settings`` so they
can be changed via environment variables without touching application code.
"""

import logging

import boto3

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# S3 bucket name — sourced from configuration, not hardcoded.
# ---------------------------------------------------------------------------
BUCKET: str = settings.aws_bucket

# ---------------------------------------------------------------------------
# S3 client singleton
# ---------------------------------------------------------------------------
s3_client = boto3.client(
    "s3",
    aws_access_key_id=settings.aws_access_key_id,
    aws_secret_access_key=settings.aws_secret_access_key,
    region_name=settings.region_name or "ap-southeast-2",
)

logger.debug("S3 client initialised for bucket '%s' in region '%s'.", BUCKET, settings.region_name)
