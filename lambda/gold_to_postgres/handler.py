from __future__ import annotations

import json
import os
from typing import Any

import loader


# Core required env. The Postgres password is satisfiable by EITHER a Secrets
# Manager ARN or an inline POSTGRES_PASSWORD (checked separately below).
REQUIRED_ENV = (
    "DATA_LAKE_BUCKET",
    "GOLD_PREFIX",
)


def missing_required_env(env: dict[str, str]) -> list[str]:
    missing = [name for name in REQUIRED_ENV if not env.get(name)]
    # The loader needs a password source: a secret ARN or an inline password.
    if not env.get("POSTGRES_PASSWORD_SECRET_ARN") and not env.get("POSTGRES_PASSWORD"):
        missing.append("POSTGRES_PASSWORD_SECRET_ARN")
    return missing


def metric_tables_from_event(event: dict[str, Any]) -> list[str]:
    tables = event.get("metric_tables") or event.get("tables") or []
    if isinstance(tables, str):
        return [tables]
    return [str(table) for table in tables]


def build_load_plan(event: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    tables = metric_tables_from_event(event)
    target_date = event.get("target_date") or env.get("TARGET_DATE")
    gold_prefix = env.get("GOLD_PREFIX", "gold").strip("/")

    return {
        "bucket": env.get("DATA_LAKE_BUCKET"),
        "gold_prefix": gold_prefix,
        "target_date": target_date,
        "metric_tables": tables,
        "postgres_host": env.get("POSTGRES_HOST"),
        "postgres_db": env.get("POSTGRES_DB"),
        "postgres_user": env.get("POSTGRES_USER"),
        "postgres_password_secret_arn": env.get("POSTGRES_PASSWORD_SECRET_ARN"),
    }


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    env = os.environ
    event = event or {}
    missing = missing_required_env(env)
    plan = build_load_plan(event, env)

    if missing:
        return {
            "statusCode": 400,
            "body": {
                "loaded": False,
                "reason": "missing required environment variables",
                "missing": missing,
                "plan": plan,
            },
        }

    tables = metric_tables_from_event(event) or loader.ALL_TABLES

    # Gating: a real load runs only when GOLD_LOAD_EXECUTE is truthy AND a real
    # POSTGRES_HOST is wired. The Terraform default host "pending-postgres-host"
    # keeps the loader in dry_run until the database is provisioned.
    host = env.get("POSTGRES_HOST")
    execute = (
        _truthy(env.get("GOLD_LOAD_EXECUTE"))
        and bool(host)
        and host != "pending-postgres-host"
    )

    if not execute:
        return {
            "statusCode": 200,
            "body": {
                "loaded": False,
                "mode": "dry_run",
                "message": (
                    "Gold-to-PostgreSQL loader wiring is ready; real upserts depend "
                    "on final gold schemas."
                ),
                "plan": plan,
                "tables": tables,
            },
        }

    # --- real execute path ---
    gold_prefix = env.get("GOLD_PREFIX", "gold").strip("/")
    local_dir = env.get("GOLD_LOCAL_INPUT_DIR")
    bucket = env.get("DATA_LAKE_BUCKET")
    source = "local:{0}".format(local_dir) if local_dir else "s3://{0}/{1}".format(bucket, gold_prefix)

    conn = loader.connect(env)
    try:
        loaded_counts: dict[str, int] = {}
        for table in tables:
            if local_dir:
                rows = loader.read_gold_table_local(local_dir, gold_prefix, table)
            else:
                rows = loader.read_gold_table_s3(bucket, gold_prefix, table)
            prepared = loader.prepare_rows(table, rows)
            loaded_counts[table] = loader.upsert_rows(conn, table, prepared)
        conn.commit()
    finally:
        conn.close()

    return {
        "statusCode": 200,
        "body": {
            "loaded": True,
            "mode": "execute",
            "source": source,
            "loaded_counts": loaded_counts,
            "total_rows": sum(loaded_counts.values()),
            "target_host": host,
        },
    }


if __name__ == "__main__":
    print(json.dumps(lambda_handler({"metric_tables": []}, None), indent=2))
