"""Silver-layer normalization Lambda (Vukan's slice).

Reads a day's raw bronze for both sources, normalizes them (``normalize.py``)
into the frozen silver schema (``lambda/gold/silver_contract.py``), and writes
the ``users`` / ``posts`` datasets the gold layer consumes:

    s3://<DATA_LAKE_BUCKET>/<SILVER_PREFIX>/users/   (Parquet dataset)
    s3://<DATA_LAKE_BUCKET>/<SILVER_PREFIX>/posts/   (Parquet dataset)

Like the bronze/gold handlers this is thin and runs three ways. Bronze is raw
JSONL, so it is read with plain boto3 ``get_object`` (no awswrangler); pandas /
awswrangler / boto3 are imported lazily and only on the path that needs them, so
the module imports (and unit tests run) without them:

    python lambda/silver/handler.py                                   # dry run
    BRONZE_LOCAL_DIR=in SILVER_LOCAL_OUTPUT_DIR=out ...               # offline file I/O
    DATA_LAKE_BUCKET=bucket ...                                       # real bronze -> silver Parquet

The local output is FLAT ``users.jsonl`` / ``posts.jsonl`` so it plugs straight
into the gold handler's ``SILVER_LOCAL_DIR``.
"""

from __future__ import annotations

import json
import os

import normalize

# pandas nullable dtypes, applied before writing Parquet so that all-null columns
# (e.g. karma for X rows, followers for HN rows) keep a stable type and HN + X
# rows share one Arrow schema when gold reads the two datasets back combined.
USERS_DTYPES = {
    "user_id": "string",
    "username": "string",
    "platform": "string",
    "karma_score": "Int64",
    "is_verified": "boolean",
    "followers_count": "Int64",
    "created_at": "string",
}
POSTS_DTYPES = {
    "post_id": "string",
    "platform": "string",
    "author_username": "string",
    "content_text": "string",
    "created_at": "string",
    "post_type": "string",
    "score": "Int64",
}


def _resolve_ingestion_date(env, today=None):
    override = env.get("INGESTION_DATE")
    if override:
        return override.strip()
    if today is None:
        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).date()
    return today.isoformat()


def _enrich_settings(env):
    """Resolve the HN user-enrichment controls from the environment."""
    raw = (env.get("HN_ENRICH_USERS") or "").strip().lower()
    enrich = raw not in ("0", "false", "no")
    limit_raw = env.get("HN_USER_ENRICH_LIMIT")
    if limit_raw is None or limit_raw.strip() == "":
        limit = normalize.DEFAULT_ENRICH_LIMIT
    else:
        limit = int(limit_raw)  # "0" -> unlimited
    return enrich, limit


def _bronze_keys(prefix, ingestion_date):
    base = "{0}/{{source}}/ingestion_date={1}".format(prefix.strip("/"), ingestion_date)
    return {
        "hn": "{0}/raw_items.jsonl".format(base.format(source="hacker_news")),
        "x": "{0}/raw_dataset.jsonl".format(base.format(source="x")),
    }


def _parse_jsonl(blob):
    records = []
    for line in blob.splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def _read_bronze_local(local_dir, keys):
    """Read raw bronze JSONL from a local dir mirroring the S3 key layout.

    A source whose file is absent is skipped gracefully (empty list).
    """
    out = {}
    for source, key in keys.items():
        path = os.path.join(local_dir, *key.split("/"))
        if os.path.isfile(path):
            with open(path, "rb") as handle:
                out[source] = _parse_jsonl(handle.read())
        else:
            out[source] = []
    return out


def _read_bronze_s3(bucket, keys):
    """Read raw bronze JSONL from S3 with plain boto3 (no awswrangler)."""
    import boto3  # lazy: real path only
    from botocore.exceptions import ClientError

    s3 = boto3.client("s3")
    out = {}
    for source, key in keys.items():
        try:
            response = s3.get_object(Bucket=bucket, Key=key)
        except ClientError:
            out[source] = []  # source not present for this partition -> skip
            continue
        out[source] = _parse_jsonl(response["Body"].read())
    return out


def _frame(rows, dtypes):
    """Build a typed, contract-ordered DataFrame for the Parquet write."""
    import pandas as pd

    columns = list(dtypes)
    df = pd.DataFrame(rows, columns=columns)
    df = df.reindex(columns=columns)
    return df.astype(dtypes)


def _write_silver_s3(bucket, silver_prefix, users, posts):
    import awswrangler as wr  # lazy

    base = "s3://{0}/{1}".format(bucket, silver_prefix.strip("/"))
    written = {}
    for name, rows, dtypes in (
        ("users", users, USERS_DTYPES),
        ("posts", posts, POSTS_DTYPES),
    ):
        path = "{0}/{1}/".format(base, name)
        wr.s3.to_parquet(
            df=_frame(rows, dtypes),
            path=path,
            dataset=True,
            mode="overwrite",
        )
        written[name] = {"path": path, "rows": len(rows)}
    return written


def _write_silver_local(directory, users, posts):
    """Write FLAT users.jsonl / posts.jsonl (plugs into gold SILVER_LOCAL_DIR)."""
    os.makedirs(directory, exist_ok=True)
    written = {}
    for name, rows in (("users", users), ("posts", posts)):
        dest = os.path.join(directory, "{0}.jsonl".format(name))
        with open(dest, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=False))
                handle.write("\n")
        written[name] = {"path": dest, "rows": len(rows)}
    return written


def lambda_handler(event, context=None, fetch_json=None):
    env = os.environ
    ingestion_date = _resolve_ingestion_date(env)
    bronze_prefix = env.get("BRONZE_PREFIX", "bronze")
    silver_prefix = env.get("SILVER_PREFIX", "silver")
    bucket = env.get("DATA_LAKE_BUCKET") or env.get("BRONZE_BUCKET")
    bronze_local = env.get("BRONZE_LOCAL_DIR")
    silver_local = env.get("SILVER_LOCAL_OUTPUT_DIR")
    enrich, enrich_limit = _enrich_settings(env)
    fetch_json = normalize.fetch_json if fetch_json is None else fetch_json

    keys = _bronze_keys(bronze_prefix, ingestion_date)

    # --- read bronze ---
    if bronze_local:
        raw = _read_bronze_local(bronze_local, keys)
        source = "local:{0}".format(bronze_local)
    elif bucket:
        raw = _read_bronze_s3(bucket, keys)
        source = "s3://{0}/{1}".format(bucket, bronze_prefix)
    else:
        raw = {"hn": [], "x": []}
        source = "none"

    # --- normalize ---
    users, posts = normalize.normalize(
        raw.get("hn", []),
        raw.get("x", []),
        fetch_json=fetch_json,
        enrich=enrich,
        enrich_limit=enrich_limit,
    )

    # --- write silver ---
    #   bucket set (and no BRONZE_LOCAL_DIR) -> Parquet datasets in S3
    #   BRONZE_LOCAL_DIR + SILVER_LOCAL_OUTPUT_DIR -> flat JSONL on disk
    #   otherwise -> dry run (write nothing)
    if bucket and not bronze_local:
        written = _write_silver_s3(bucket, silver_prefix, users, posts)
        sink = "s3"
    elif silver_local:
        written = _write_silver_local(silver_local, users, posts)
        sink = "local"
    else:
        written = None
        sink = "none"

    return {
        "statusCode": 200,
        "body": {
            "ingestion_date": ingestion_date,
            "source": source,
            "sink": sink,
            "input_counts": {"hn": len(raw.get("hn", [])), "x": len(raw.get("x", []))},
            "output_counts": {"users": len(users), "posts": len(posts)},
            "written": written,
        },
    }


if __name__ == "__main__":
    result = lambda_handler({}, None)
    print(json.dumps(result["body"], indent=2, default=str))
