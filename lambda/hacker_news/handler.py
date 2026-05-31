"""Bronze-layer ingestion Lambda for the Hacker News source.

Vukan's ingestion path. The handler is intentionally thin: it resolves the
shared environment-variable contract, collects the previous day's raw Hacker
News items from the Algolia HN Search API, builds ``metadata.json``, and writes
both objects to S3 under the shared bronze layout:

    s3://<BRONZE_BUCKET>/<BRONZE_PREFIX>/hacker_news/ingestion_date=YYYY-MM-DD/
        ├── metadata.json
        └── raw_items.jsonl

Bronze rule: items are stored exactly as the API returns them (one JSON object
per line). No HTML cleaning, timestamp normalization, field flattening, schema
mapping, or deduplication.

This module doubles as a repeatable local script:

    # dry run (no network, no AWS) — prints the keys/dates it would write
    python lambda/hacker_news/handler.py

    # offline sample run — fetches the real previous day and writes the bronze
    # layout to local disk (needs network, no AWS):
    HN_LOCAL_OUTPUT_DIR=build/sample-out python lambda/hacker_news/handler.py

    # real upload (needs network + AWS creds + a writable BRONZE_BUCKET):
    BRONZE_BUCKET=my-bucket python lambda/hacker_news/handler.py

``boto3`` is imported lazily so the module can be imported (and unit tested)
without boto3 or AWS credentials present.
"""

from __future__ import annotations

import json
import os

import hn_ingest


def _write_outputs(bucket, local_dir, keys, raw_bytes, metadata_bytes):
    """Write the raw items + metadata to the chosen sink, preserving the layout.

    Returns the sink name ("s3" or "local"). S3 takes precedence when a bucket
    is set.
    """
    if bucket:
        import boto3  # lazy: only needed for the real upload path

        s3 = boto3.client("s3")
        s3.put_object(Bucket=bucket, Key=keys["raw_key"], Body=raw_bytes, ContentType="application/x-ndjson")
        s3.put_object(Bucket=bucket, Key=keys["metadata_key"], Body=metadata_bytes, ContentType="application/json")
        return "s3"

    # Local filesystem sink mirroring the exact S3 key layout. Lets a sample run
    # produce raw_items.jsonl + metadata.json and demonstrate the bronze layout
    # without AWS.
    for key, body in ((keys["raw_key"], raw_bytes), (keys["metadata_key"], metadata_bytes)):
        dest = os.path.join(local_dir, *key.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as handle:
            handle.write(body)
    return "local"


def lambda_handler(event, context=None, fetcher=None):
    env = os.environ

    ingestion_date = hn_ingest.resolve_ingestion_date(env)
    target_date = hn_ingest.resolve_target_date(env, ingestion_date)
    prefix = hn_ingest.bronze_prefix(env)
    bucket = env.get("BRONZE_BUCKET")
    local_dir = env.get("HN_LOCAL_OUTPUT_DIR")
    keys = hn_ingest.build_object_keys(ingestion_date, prefix)

    # Sink selection:
    #   BRONZE_BUCKET set        -> fetch + upload to S3 (real ingestion / Lambda runtime)
    #   HN_LOCAL_OUTPUT_DIR set  -> fetch + write the same key layout to local disk
    #                               (offline sample run / bronze-layout demo)
    #   neither                  -> dry run: no network, no AWS; report the plan only
    if not bucket and not local_dir:
        return {
            "statusCode": 200,
            "body": {
                "dry_run": True,
                "sink": "none",
                "bucket": None,
                "target_date": target_date,
                "ingestion_date": ingestion_date,
                "keys": keys,
            },
        }

    start, end = hn_ingest.day_epoch_bounds(target_date)
    hits = hn_ingest.fetch_day_hits(target_date, fetcher=fetcher)
    # Client-side guard: keep only items actually created on the target day.
    hits = hn_ingest.filter_hits_within_day(hits, start, end)

    raw_bytes = hn_ingest.to_jsonl(hits)
    counts_by_type = hn_ingest.count_by_type(hits)
    metadata = hn_ingest.build_metadata(
        target_date=target_date,
        ingestion_date=ingestion_date,
        record_count=len(hits),
        counts_by_type=counts_by_type,
    )
    metadata_bytes = (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode("utf-8")

    sink = _write_outputs(bucket, local_dir, keys, raw_bytes, metadata_bytes)

    return {
        "statusCode": 200,
        "body": {
            "dry_run": False,
            "sink": sink,
            "bucket": bucket,
            "output_dir": local_dir if sink == "local" else None,
            "target_date": target_date,
            "ingestion_date": ingestion_date,
            "record_count": len(hits),
            "counts_by_type": counts_by_type,
            "raw_key": keys["raw_key"],
            "metadata_key": keys["metadata_key"],
        },
    }


if __name__ == "__main__":
    result = lambda_handler({}, None)
    print(json.dumps(result["body"], indent=2, default=str))
