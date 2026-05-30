from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os


def _date_or_default(name: str, default: str) -> str:
    return os.environ.get(name, default)


def lambda_handler(event, context):
    ingestion_date = datetime.now(timezone.utc).date()
    target_date = ingestion_date - timedelta(days=1)
    bronze_prefix = os.environ.get("BRONZE_PREFIX", "bronze").strip("/")

    raw_key = (
        f"{bronze_prefix}/hacker_news/"
        f"ingestion_date={_date_or_default('INGESTION_DATE', ingestion_date.isoformat())}/"
        "raw_items.jsonl"
    )
    metadata_key = raw_key.rsplit("/", 1)[0] + "/metadata.json"

    return {
        "statusCode": 200,
        "body": {
            "message": "Hacker News bronze Lambda skeleton is wired. Vukan will add API ingestion logic.",
            "bucket": os.environ.get("BRONZE_BUCKET"),
            "target_date": _date_or_default("TARGET_DATE", target_date.isoformat()),
            "raw_key": raw_key,
            "metadata_key": metadata_key,
        },
    }
