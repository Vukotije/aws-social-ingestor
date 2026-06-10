"""Gold-to-PostgreSQL loader core (Marko's slice).

Pure, unit-testable SQL/row logic plus lazy I/O. Like the gold handler, every
heavy or networked dependency (psycopg2, boto3, awswrangler) is imported lazily
and only on the real execute path, so this module imports — and its unit tests
run — with nothing but the standard library.

The gold tables, their column order, and PRIMARY KEYs mirror db/gold_metrics.sql
(the schema Superset reads) and the gold Parquet datasets from lambda/gold.
"""

from __future__ import annotations

import os


# Column order + primary key per gold table, mirroring db/gold_metrics.sql.
# "cols" is the INSERT column order; "pk" is the ON CONFLICT target.
TABLE_SPECS = {
    "daily_hn_item_counts": {
        "cols": ["metric_date", "post_type", "item_count"],
        "pk": ["metric_date", "post_type"],
    },
    "daily_users_metric": {
        "cols": [
            "metric_date", "platform", "new_users", "total_users",
            "active_users", "post_count", "comment_count",
        ],
        "pk": ["metric_date", "platform"],
    },
    "top_x_users_by_followers": {
        "cols": ["metric_date", "rank", "username", "followers_count", "is_verified"],
        "pk": ["metric_date", "rank"],
    },
    "top_hn_users_by_karma_high": {
        "cols": ["metric_date", "rank", "username", "karma_score"],
        "pk": ["metric_date", "rank"],
    },
    "top_hn_users_by_karma_low": {
        "cols": ["metric_date", "rank", "username", "karma_score"],
        "pk": ["metric_date", "rank"],
    },
    "top_hn_jobs_by_score": {
        "cols": ["metric_date", "rank", "post_id", "score", "author_username", "content_text"],
        "pk": ["metric_date", "rank"],
    },
    "top_hn_stories_by_score": {
        "cols": ["metric_date", "rank", "post_id", "score", "author_username", "content_text"],
        "pk": ["metric_date", "rank"],
    },
    "data_quality_score": {
        "cols": [
            "metric_date", "source", "total_records", "valid_records",
            "invalid_records", "quality_score",
        ],
        "pk": ["metric_date", "source"],
    },
}

ALL_TABLES = list(TABLE_SPECS)


# --- SQL / row logic (pure) ---------------------------------------------------

def build_upsert_sql(table):
    """Return an INSERT ... ON CONFLICT upsert for ``table``.

    Uses a ``VALUES %s`` placeholder for psycopg2.extras.execute_values. Non-PK
    columns are refreshed from EXCLUDED; an all-PK table degrades to DO NOTHING.
    """
    spec = TABLE_SPECS[table]
    cols = spec["cols"]
    pk = spec["pk"]
    non_pk = [c for c in cols if c not in pk]

    insert = "INSERT INTO {table} ({cols}) VALUES %s ON CONFLICT ({pk}) ".format(
        table=table,
        cols=", ".join(cols),
        pk=", ".join(pk),
    )
    if non_pk:
        assignments = ", ".join("{c} = EXCLUDED.{c}".format(c=c) for c in non_pk)
        return insert + "DO UPDATE SET " + assignments
    return insert + "DO NOTHING"


def _coerce_metric_date(value):
    """Coerce a date/datetime/str metric_date to a 'YYYY-MM-DD' string (or None)."""
    if value is None:
        return None
    # date/datetime expose isoformat(); slice to the date portion.
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        return value.isoformat()[:10]
    return str(value)[:10]


def prepare_rows(table, raw_rows):
    """Project ``raw_rows`` (list of dicts) onto the table's column order.

    Keeps only TABLE_SPECS columns, coerces metric_date to a 'YYYY-MM-DD'
    string, passes scalars/None through, and defaults missing keys to None.
    Returns a list of tuples aligned to the column order.
    """
    cols = TABLE_SPECS[table]["cols"]
    rows = []
    for raw in raw_rows:
        values = []
        for col in cols:
            value = raw.get(col)
            if col == "metric_date":
                value = _coerce_metric_date(value)
            values.append(value)
        rows.append(tuple(values))
    return rows


# --- gold readers (lazy I/O) --------------------------------------------------

def read_gold_table_local(base_dir, gold_prefix, table):
    """Read ``<base_dir>/<gold_prefix>/<table>/data.json`` (a JSON list).

    Returns [] when the file is absent (mirrors the gold handler's local sink).
    """
    import json

    path = os.path.join(base_dir, gold_prefix.strip("/"), table, "data.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def read_gold_table_s3(bucket, gold_prefix, table):
    """Read the gold Parquet dataset ``s3://bucket/<gold_prefix>/<table>/``.

    Partition columns (metric_date/platform) come back as columns. Returns []
    when the prefix holds no objects yet.
    """
    import awswrangler as wr  # lazy: real path only

    path = "s3://{0}/{1}/{2}/".format(bucket, gold_prefix.strip("/"), table)
    try:
        df = wr.s3.read_parquet(path, dataset=True)
    except Exception as exc:  # no objects under the prefix yet
        message = str(exc).lower()
        if "no files" in message or "no objects" in message or "empty" in message:
            return []
        raise
    return df.to_dict("records")


# --- upsert / connection (lazy I/O) -------------------------------------------

def upsert_rows(conn, table, rows, execute_values=None):
    """Upsert ``rows`` (list of tuples) into ``table``; return the row count.

    Caller commits. ``execute_values`` may be injected (tests pass a fake) to
    avoid importing psycopg2.
    """
    if not rows:
        return 0
    if execute_values is None:
        from psycopg2.extras import execute_values as _ev  # lazy
    else:
        _ev = execute_values
    sql = build_upsert_sql(table)
    with conn.cursor() as cur:
        _ev(cur, sql, rows)
    return len(rows)


def _resolve_password(env):
    """Return the Postgres password: env POSTGRES_PASSWORD, else Secrets Manager."""
    password = env.get("POSTGRES_PASSWORD")
    if password:
        return password
    import boto3  # lazy

    secret_arn = env.get("POSTGRES_PASSWORD_SECRET_ARN")
    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=secret_arn)
    return response["SecretString"]


def connect(env):
    """Open a psycopg2 connection from environment configuration."""
    import psycopg2  # lazy

    return psycopg2.connect(
        host=env.get("POSTGRES_HOST"),
        port=int(env.get("POSTGRES_PORT", "5432")),
        dbname=env.get("POSTGRES_DB"),
        user=env.get("POSTGRES_USER"),
        password=_resolve_password(env),
        connect_timeout=10,
    )
