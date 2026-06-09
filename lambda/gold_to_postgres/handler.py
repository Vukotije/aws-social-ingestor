from __future__ import annotations

import json
import os
from typing import Any


REQUIRED_ENV = (
    "DATA_LAKE_BUCKET",
    "GOLD_PREFIX",
    "POSTGRES_PASSWORD_SECRET_ARN",
)


def missing_required_env(env: dict[str, str]) -> list[str]:
    return [name for name in REQUIRED_ENV if not env.get(name)]


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


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    env = os.environ
    missing = missing_required_env(env)
    plan = build_load_plan(event or {}, env)

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

    # This slice proves the orchestration and secret/network contract. The actual
    # PostgreSQL insert/upsert implementation is added once gold schemas settle.
    return {
        "statusCode": 200,
        "body": {
            "loaded": False,
            "mode": "dry_run",
            "message": "Gold-to-PostgreSQL loader wiring is ready; real upserts depend on final gold schemas.",
            "plan": plan,
        },
    }


if __name__ == "__main__":
    print(json.dumps(lambda_handler({"metric_tables": []}, None), indent=2))
