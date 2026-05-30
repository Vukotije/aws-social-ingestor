"""Bronze-layer ingestion logic for the X/Twitter-style dataset.

This module holds the pure, AWS-free logic so it can be unit tested locally
without boto3 or AWS credentials. The Lambda handler in ``handler.py`` is a thin
wrapper that resolves environment variables, calls these helpers, and performs
the S3 ``put_object`` calls.

Bronze-layer rule: the dataset is stored in S3 in its original/raw form. Nothing
here normalizes, cleans, deduplicates, reorders, or transforms the dataset
bytes. ``count_records`` only *reads* the bytes to report a row count for
metadata; the stored object is always the original file, byte for byte.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os

# --- Dataset identity / provenance (see lambda/x/README.md for full notes) ---
DATASET_NAME = "x-twitter-sample-2026"
DATASET_PROVENANCE = (
    "Synthetic X/Twitter-style sample, manually authored by the team for the "
    "bronze control point. Not collected from the live X/Twitter API (the free "
    "API tier is too limited, which the project spec explicitly allows working "
    "around with existing/generated datasets). Each record mirrors the public "
    "X API v2 tweet object shape (nested user object + public_metrics, ISO-8601 "
    "created_at) so downstream silver normalization has realistic raw input."
)
DATASET_FORMAT = "jsonl"

# Name of the bundled source dataset inside the Lambda package.
DEFAULT_DATASET_FILENAME = "x_sample_tweets.jsonl"
# Name of the object written to S3 (shared bronze contract: raw_dataset.<ext>).
RAW_OBJECT_NAME = "raw_dataset.jsonl"


def default_dataset_path() -> str:
    """Absolute path to the dataset bundled alongside this module."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "dataset", DEFAULT_DATASET_FILENAME)


def bronze_prefix(env=None) -> str:
    """Return the bronze prefix from the environment (defaults to ``bronze``)."""
    env = os.environ if env is None else env
    return env.get("BRONZE_PREFIX", "bronze").strip("/")


def resolve_ingestion_date(env=None, today=None) -> str:
    """Resolve the ingestion date as ``YYYY-MM-DD``.

    Honors the shared ``INGESTION_DATE`` override used for testing; otherwise
    uses the current UTC date. ``today`` is injectable so callers/tests stay
    deterministic.
    """
    env = os.environ if env is None else env
    override = env.get("INGESTION_DATE")
    if override:
        return override.strip()
    if today is None:
        today = datetime.now(timezone.utc).date()
    return today.isoformat()


def build_object_keys(ingestion_date, prefix="bronze") -> dict:
    """Build the shared-contract S3 keys for the X bronze output.

    Layout:
        <prefix>/x/ingestion_date=YYYY-MM-DD/raw_dataset.jsonl
        <prefix>/x/ingestion_date=YYYY-MM-DD/metadata.json
    """
    base = "{prefix}/x/ingestion_date={date}".format(
        prefix=prefix.strip("/"), date=ingestion_date
    )
    return {
        "base": base,
        "raw_key": "{base}/{name}".format(base=base, name=RAW_OBJECT_NAME),
        "metadata_key": "{base}/metadata.json".format(base=base),
    }


def count_records(raw_bytes: bytes) -> int:
    """Count records in the raw JSONL dataset (one record per non-empty line).

    Read-only: this never mutates or re-serializes the data.
    """
    return sum(1 for line in raw_bytes.splitlines() if line.strip())


def build_metadata(ingestion_date, row_count, byte_count, raw_key, target_date=None) -> dict:
    """Build the X ``metadata.json`` payload.

    Contains every field required by the spec: dataset name, provenance, format,
    ingestion date, and row/file count.
    """
    metadata = {
        "dataset_name": DATASET_NAME,
        "provenance": DATASET_PROVENANCE,
        "format": DATASET_FORMAT,
        "ingestion_date": ingestion_date,
        "row_count": row_count,
        "file_count": 1,
        "byte_count": byte_count,
        "object_key": raw_key,
        "raw": True,
    }
    if target_date:
        metadata["target_date"] = target_date.strip()
    return metadata
