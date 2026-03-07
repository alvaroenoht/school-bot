"""
S3 upload utilities — upload PDF reports and generate presigned download URLs.
Uses AWS credentials from .env (already configured for Textract).
"""
import logging

import boto3

from app.config import get_settings

logger = logging.getLogger(__name__)


def _get_s3_client():
    settings = get_settings()
    return boto3.client(
        "s3",
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
    )


def upload_file_to_s3(file_path: str, s3_key: str, bucket: str | None = None) -> None:
    """Upload a local file to S3."""
    if bucket is None:
        bucket = get_settings().s3_bucket
    client = _get_s3_client()
    client.upload_file(file_path, bucket, s3_key)
    logger.info(f"Uploaded {file_path} → s3://{bucket}/{s3_key}")


def generate_presigned_url(
    s3_key: str,
    bucket: str | None = None,
    expiration: int = 604800,  # 7 days
) -> str:
    """Generate a presigned URL for downloading a file from S3."""
    if bucket is None:
        bucket = get_settings().s3_bucket
    client = _get_s3_client()
    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": s3_key},
        ExpiresIn=expiration,
    )
    return url
