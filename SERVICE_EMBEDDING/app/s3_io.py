"""
s3_io.py — S3 helpers: list images, download as PIL, upload CSV.
"""

import csv
import io
import logging
from datetime import datetime, timezone

import boto3
from PIL import Image

from app import config

logger = logging.getLogger(__name__)

_s3 = boto3.client("s3")


def list_input_images() -> list[str]:
    """
    Return all .png object keys under INPUT_BUCKET/INPUT_PREFIX.
    Uses paginator so it works with >1000 objects.
    """
    paginator = _s3.get_paginator("list_objects_v2")
    pages     = paginator.paginate(Bucket=config.INPUT_BUCKET, Prefix=config.INPUT_PREFIX)

    keys = []
    for page in pages:
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.lower().endswith(".png") and not key.endswith("/"):
                keys.append(key)

    logger.info(
        "Found %d PNG images in s3://%s/%s",
        len(keys), config.INPUT_BUCKET, config.INPUT_PREFIX,
    )
    return keys


def download_image(key: str) -> Image.Image:
    """Download an S3 object and return it as a PIL Image (RGB)."""
    response = _s3.get_object(Bucket=config.INPUT_BUCKET, Key=key)
    data     = response["Body"].read()
    return Image.open(io.BytesIO(data)).convert("RGB")


def upload_results_csv(rows: list[dict]) -> str:
    """
    Serialise *rows* as a UTF-8 CSV and upload to
    s3://OUTPUT_BUCKET/OUTPUT_PREFIX/results_<timestamp>.csv

    Returns the full s3:// URI.
    """
    if not rows:
        raise ValueError("No results to upload.")

    ts  = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    key = f"{config.OUTPUT_PREFIX.rstrip('/')}/results_{ts}.csv"

    fieldnames = list(rows[0].keys())
    buf        = io.StringIO()
    writer     = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)

    _s3.put_object(
        Bucket=config.OUTPUT_BUCKET,
        Key=key,
        Body=buf.getvalue().encode("utf-8"),
        ContentType="text/csv",
    )

    uri = f"s3://{config.OUTPUT_BUCKET}/{key}"
    logger.info("Uploaded %d results → %s", len(rows), uri)
    return uri
