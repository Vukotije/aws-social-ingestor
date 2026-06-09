"""Gold-layer transformation Lambda (Marko's slice).

Reads the normalized silver ``users`` and ``posts`` datasets, computes every
required metric and the Data Quality Score KPI (see ``metrics.py``), and writes
each gold table as partitioned Parquet under the shared gold prefix:

    s3://<DATA_LAKE_BUCKET>/<GOLD_PREFIX>/<table>/metric_date=YYYY-MM-DD/...

Like the bronze handlers this is thin: pandas/awswrangler are imported lazily and
only on the real S3 path, so the module imports (and unit tests run) without
them. It also runs offline:

    python lambda/gold/handler.py                       # dry run on bundled sample
    SILVER_LOCAL_DIR=dir GOLD_LOCAL_OUTPUT_DIR=out ...   # offline file I/O
    DATA_LAKE_BUCKET=bucket ...                          # real silver -> gold Parquet
"""

from __future__ import annotations

import json
import os

import metrics


def _resolve_metric_date(env, today=None):
    for key in ("TARGET_DATE", "INGESTION_DATE"):
        value = env.get(key)
        if value:
            return value.strip()
    if today is None:
        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).date()
    return today.isoformat()


def default_sample_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "sample_silver")


def _read_jsonl(path):
    records = []
    with open(path, "rb") as handle:
        for line in handle.read().splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _load_silver_local(directory):
    users = _read_jsonl(os.path.join(directory, "users.jsonl"))
    posts = _read_jsonl(os.path.join(directory, "posts.jsonl"))
    return users, posts


def _load_silver_s3(bucket, silver_prefix):
    import awswrangler as wr  # lazy: real path only

    base = "s3://{0}/{1}".format(bucket, silver_prefix.strip("/"))
    users = wr.s3.read_parquet("{0}/users/".format(base), dataset=True).to_dict("records")
    posts = wr.s3.read_parquet("{0}/posts/".format(base), dataset=True).to_dict("records")
    return users, posts


def _write_gold_s3(bucket, gold_prefix, tables):
    import awswrangler as wr  # lazy
    import pandas as pd

    written = {}
    base = "s3://{0}/{1}".format(bucket, gold_prefix.strip("/"))
    for name, rows in tables.items():
        path = "{0}/{1}/".format(base, name)
        df = pd.DataFrame(rows)
        partition_cols = [c for c in metrics.PARTITION_COLS.get(name, []) if c in df.columns]
        wr.s3.to_parquet(
            df=df,
            path=path,
            dataset=True,
            mode="overwrite_partitions" if partition_cols else "overwrite",
            partition_cols=partition_cols,
        )
        written[name] = {"path": path, "rows": len(rows)}
    return written


def _write_gold_local(directory, gold_prefix, tables):
    written = {}
    for name, rows in tables.items():
        dest = os.path.join(directory, gold_prefix.strip("/"), name, "data.json")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as handle:
            json.dump(rows, handle, indent=2, sort_keys=True)
        written[name] = {"path": dest, "rows": len(rows)}
    return written


def lambda_handler(event, context=None):
    env = os.environ
    metric_date = _resolve_metric_date(env)
    silver_prefix = env.get("SILVER_PREFIX", "silver")
    gold_prefix = env.get("GOLD_PREFIX", "gold")
    bucket = env.get("DATA_LAKE_BUCKET") or env.get("BRONZE_BUCKET")
    silver_local = env.get("SILVER_LOCAL_DIR")
    gold_local = env.get("GOLD_LOCAL_OUTPUT_DIR")

    # --- load silver ---
    if silver_local:
        users, posts = _load_silver_local(silver_local)
        source = "local:{0}".format(silver_local)
    elif bucket:
        users, posts = _load_silver_s3(bucket, silver_prefix)
        source = "s3://{0}/{1}".format(bucket, silver_prefix)
    else:
        users, posts = _load_silver_local(default_sample_dir())
        source = "sample"

    tables = metrics.compute_all(users, posts, metric_date)
    summary = {name: len(rows) for name, rows in tables.items()}

    # --- write gold ---
    if bucket and not silver_local:
        written = _write_gold_s3(bucket, gold_prefix, tables)
        sink = "s3"
    elif gold_local:
        written = _write_gold_local(gold_local, gold_prefix, tables)
        sink = "local"
    else:
        written = None
        sink = "none"

    return {
        "statusCode": 200,
        "body": {
            "metric_date": metric_date,
            "silver_source": source,
            "sink": sink,
            "input_counts": {"users": len(users), "posts": len(posts)},
            "table_row_counts": summary,
            "written": written,
            "tables": tables if sink == "none" else None,
        },
    }


if __name__ == "__main__":
    body = dict(lambda_handler({}, None)["body"])
    body.pop("tables", None)  # trim the full dump for a readable dry-run print
    print(json.dumps(body, indent=2, default=str))
