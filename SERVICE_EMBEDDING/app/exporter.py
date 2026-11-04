"""
exporter.py — Write a list of dicts to S3 as a UTF-8 CSV file.
"""

import csv
import io
import logging
from datetime import datetime, timezone

import boto3

from app import config

logger = logging.getLogger(__name__)


def export_to_s3(rows: list[dict]) -> str:
    """
    Serialise *rows* as a CSV and upload to S3.

    Returns the full s3:// URI of the uploaded object.
    Raises if rows is empty (nothing to export).
    """
    if not rows:
        raise ValueError("No rows to export — aborting S3 upload.")

    # ------------------------------------------------------------------ #
    # Build CSV in memory                                                  #
    # ------------------------------------------------------------------ #
    fieldnames = list(rows[0].keys())
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)

    csv_bytes = buffer.getvalue().encode("utf-8")

    # ------------------------------------------------------------------ #
    # Compose a timestamped S3 key                                         #
    # ------------------------------------------------------------------ #
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    key = f"{config.S3_KEY_PREFIX.rstrip('/')}/{config.DB_TABLE}_{ts}.csv"

    # ------------------------------------------------------------------ #
    # Upload                                                               #
    # ------------------------------------------------------------------ #
    s3 = boto3.client("s3")
    s3.put_object(
        Bucket=config.S3_BUCKET,
        Key=key,
        Body=csv_bytes,
        ContentType="text/csv",
    )

    s3_uri = f"s3://{config.S3_BUCKET}/{key}"
    logger.info("Exported %d rows → %s", len(rows), s3_uri)
    return s3_uri
