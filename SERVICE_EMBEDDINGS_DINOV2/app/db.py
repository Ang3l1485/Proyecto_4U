"""
db.py — RDS IAM token authentication + psycopg2 helpers.

IAM auth flow:
  1. boto3 generates a short-lived (15 min) auth token using the task's
     IAM role (no static password stored anywhere).
  2. psycopg2 connects to the cluster endpoint using that token as the
     password, with SSL required.
"""

import ast
import logging

import boto3
import numpy as np
import psycopg2
from psycopg2.extras import RealDictCursor

from app import config

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Connection helpers                                                   #
# ------------------------------------------------------------------ #

def _generate_iam_token() -> str:
    """Ask RDS to sign a temporary auth token for the current IAM identity."""
    client = boto3.client("rds", region_name=config.DB_REGION)
    token = client.generate_db_auth_token(
        DBHostname=config.DB_HOST,
        Port=config.DB_PORT,
        DBUsername=config.DB_USER,
        Region=config.DB_REGION,
    )
    logger.debug("IAM auth token generated (valid 15 min).")
    return token


def get_connection() -> psycopg2.extensions.connection:
    """Return a psycopg2 connection authenticated via IAM token."""
    token = _generate_iam_token()
    conn = psycopg2.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=token,
        dbname=config.DB_NAME,
        sslmode="require",
    )
    logger.info(
        "Connected to %s:%s/%s as %s",
        config.DB_HOST, config.DB_PORT, config.DB_NAME, config.DB_USER,
    )
    return conn


# ------------------------------------------------------------------ #
# Data fetchers                                                        #
# ------------------------------------------------------------------ #

def fetch_reference_embeddings() -> tuple[np.ndarray, list[dict]]:
    """
    Load all rows from train_embeddings and return:
      - matrix  : np.ndarray of shape (N, embedding_dim), float32, L2-normalised
      - metadata: list of dicts with keys id, id_point, image_name

    The 'embedding' column is expected to be a text column containing a
    Python-list literal, e.g. '[0.123, -0.456, ...]', same format that
    was used when writing the CSV.
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            sql = f"SELECT id, id_point, image_name, embedding FROM {config.EMBEDDINGS_TABLE};"
            logger.info("Loading reference embeddings: %s", sql)
            cur.execute(sql)
            rows = cur.fetchall()

    logger.info("Fetched %d reference embeddings from DB.", len(rows))

    vectors  = []
    metadata = []
    for row in rows:
        vec = np.array(ast.literal_eval(row["embedding"]), dtype=np.float32)
        # L2-normalise so dot product == cosine similarity
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        vectors.append(vec)
        metadata.append({
            "id":         row["id"],
            "id_point":   row["id_point"],
            "image_name": row["image_name"],
        })

    matrix = np.vstack(vectors)   # shape: (N, D)
    return matrix, metadata


def fetch_location_names() -> dict[int, str]:
    """
    Return a mapping  {point_id -> location_name}
    from the locations_info table.
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            sql = f"SELECT id, name FROM {config.LOCATIONS_TABLE};"
            logger.info("Loading location names: %s", sql)
            cur.execute(sql)
            rows = cur.fetchall()

    mapping = {row["id"]: row["name"] for row in rows}
    logger.info("Loaded %d location names.", len(mapping))
    return mapping
