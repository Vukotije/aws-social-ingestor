"""Bronze-layer ingestion Lambda for the X/Twitter-style dataset.

Marko's ingestion path. The handler is intentionally thin: it resolves the
shared environment-variable contract, loads the bundled raw dataset, builds
``metadata.json``, and writes both objects to S3 under the shared bronze layout:

    s3://<BRONZE_BUCKET>/<BRONZE_PREFIX>/x/ingestion_date=YYYY-MM-DD/
        ├── metadata.json
        └── raw_dataset.jsonl

Bronze rule: the dataset is uploaded byte-for-byte in its original form. No
normalization, cleaning, deduplication, timestamp conversion, or Parquet.

This module doubles as a repeatable local script:

    # dry run (no upload) — prints what would be written
    python lambda/x/handler.py

    # real upload (needs AWS creds + a writable BRONZE_BUCKET)
    BRONZE_BUCKET=my-bucket python lambda/x/handler.py

``boto3`` is imported lazily so the module can be imported (and unit tested)
without boto3 or AWS credentials present.
"""

from __future__ import annotations

import json
import os

import x_ingest


def _load_dataset_bytes(env):
    """Read the raw dataset bytes. ``X_DATASET_PATH`` overrides the bundled file."""
    path = env.get("X_DATASET_PATH") or x_ingest.default_dataset_path()
    with open(path, "rb") as handle:
        return path, handle.read()


def _write_outputs(bucket, local_dir, keys, raw_bytes, metadata_bytes):
    """Write the raw dataset + metadata to the chosen sink, preserving the key layout.

    Returns the sink name ("s3" or "local"). S3 takes precedence when a bucket is set.
    """
    if bucket:
        import boto3  # lazy: only needed for the real upload path

        s3 = boto3.client("s3")
        s3.put_object(Bucket=bucket, Key=keys["raw_key"], Body=raw_bytes, ContentType="application/x-ndjson")
        s3.put_object(Bucket=bucket, Key=keys["metadata_key"], Body=metadata_bytes, ContentType="application/json")
        return "s3"

    # Local filesystem sink mirroring the exact S3 key layout. Lets a sample run
    # produce raw_dataset.jsonl + metadata.json and demonstrate the bronze layout
    # without AWS.
    for key, body in ((keys["raw_key"], raw_bytes), (keys["metadata_key"], metadata_bytes)):
        dest = os.path.join(local_dir, *key.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as handle:
            handle.write(body)
    return "local"


def lambda_handler(event, context=None):
    env = os.environ

    ingestion_date = x_ingest.resolve_ingestion_date(env)
    prefix = x_ingest.bronze_prefix(env)
    target_date = env.get("TARGET_DATE")
    bucket = env.get("BRONZE_BUCKET")
    local_dir = env.get("X_LOCAL_OUTPUT_DIR")

    dataset_path, raw_bytes = _load_dataset_bytes(env)
    row_count = x_ingest.count_records(raw_bytes)
    keys = x_ingest.build_object_keys(ingestion_date, prefix)
    metadata = x_ingest.build_metadata(
        ingestion_date=ingestion_date,
        row_count=row_count,
        byte_count=len(raw_bytes),
        raw_key=keys["raw_key"],
        target_date=target_date,
    )
    metadata_bytes = (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode("utf-8")

    # Sink selection:
    #   BRONZE_BUCKET set       -> upload to S3 (real ingestion / Lambda runtime)
    #   X_LOCAL_OUTPUT_DIR set  -> write the same key layout to local disk
    #                              (offline sample run / bronze-layout demo)
    #   neither                 -> dry run (compute + return, write nothing)
    if not bucket and not local_dir:
        return {
            "statusCode": 200,
            "body": {
                "dry_run": True,
                "sink": "none",
                "bucket": None,
                "dataset_path": dataset_path,
                "row_count": row_count,
                "keys": keys,
                "metadata": metadata,
            },
        }

    sink = _write_outputs(bucket, local_dir, keys, raw_bytes, metadata_bytes)

    return {
        "statusCode": 200,
        "body": {
            "dry_run": False,
            "sink": sink,
            "bucket": bucket,
            "output_dir": local_dir if sink == "local" else None,
            "row_count": row_count,
            "raw_key": keys["raw_key"],
            "metadata_key": keys["metadata_key"],
            "metadata": metadata,
        },
    }


if __name__ == "__main__":
    result = lambda_handler({}, None)
    print(json.dumps(result["body"], indent=2, default=str))
