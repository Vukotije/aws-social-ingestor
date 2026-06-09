"""Integration test: the gold handler's REAL S3 + Parquet path, against moto.

The unit/e2e tests exercise the pure metrics and the local JSON sink. This one
drives the handler's actual ``_load_silver_s3`` / ``_write_gold_s3`` functions —
the awswrangler Parquet I/O — against a moto-mocked S3 bucket:

    seed silver Parquet -> handler reads it -> computes -> writes gold Parquet
    -> read the gold Parquet back and assert the metrics survived the round-trip.

Requires pandas/pyarrow/moto/awswrangler (the Lambda's real deps). It SKIPS
cleanly when they are absent, so the stdlib suite is unaffected:

    /tmp/v314/bin/python tests/test_integration_gold_s3_parquet.py   # with deps
    python tests/test_integration_gold_s3_parquet.py                 # skips
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "lambda", "gold")
sys.path.insert(0, SRC)

_DEPS = ("awswrangler", "pandas", "moto", "pyarrow")
HAVE_DEPS = all(importlib.util.find_spec(m) is not None for m in _DEPS)

try:
    import pytest

    pytestmark = pytest.mark.skipif(not HAVE_DEPS, reason="requires pandas/pyarrow/moto/awswrangler")
except ImportError:
    pytest = None

BUCKET = "test-data-lake"


@contextlib.contextmanager
def env(**overrides):
    saved = {k: os.environ.get(k) for k in overrides}
    try:
        for k, v in overrides.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _read_jsonl(path):
    with open(path, "rb") as fh:
        return [json.loads(line) for line in fh.read().splitlines() if line.strip()]


def _sample_silver():
    base = os.path.join(SRC, "sample_silver")
    return _read_jsonl(os.path.join(base, "users.jsonl")), _read_jsonl(os.path.join(base, "posts.jsonl"))


def test_handler_s3_parquet_roundtrip():
    if not HAVE_DEPS:
        print("SKIPPED: pandas/pyarrow/moto/awswrangler not installed")
        return

    import awswrangler as wr
    import boto3
    import pandas as pd
    from moto import mock_aws

    import handler
    import metrics

    users, posts = _sample_silver()

    aws_env = dict(
        AWS_ACCESS_KEY_ID="testing",
        AWS_SECRET_ACCESS_KEY="testing",
        AWS_SESSION_TOKEN="testing",
        AWS_DEFAULT_REGION="us-east-1",
        AWS_REGION="us-east-1",
        DATA_LAKE_BUCKET=BUCKET,
        SILVER_LOCAL_DIR=None,
        GOLD_LOCAL_OUTPUT_DIR=None,
        BRONZE_BUCKET=None,
        INGESTION_DATE="2026-01-16",
    )

    with env(**aws_env), mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)

        # Seed silver as Parquet, standing in for Vukan's silver output.
        wr.s3.to_parquet(pd.DataFrame(users), path="s3://{0}/silver/users/".format(BUCKET), dataset=True, mode="overwrite")
        wr.s3.to_parquet(pd.DataFrame(posts), path="s3://{0}/silver/posts/".format(BUCKET), dataset=True, mode="overwrite")

        # Real handler path: read silver Parquet -> compute -> write gold Parquet.
        body = handler.lambda_handler({}, None)["body"]
        assert body["sink"] == "s3"
        assert set(body["written"]) == set(metrics.PARTITION_COLS)
        assert body["input_counts"] == {"users": len(users), "posts": len(posts)}

        # Read the gold Parquet back and confirm the metrics survived the round-trip.
        def gold(table):
            return wr.s3.read_parquet("s3://{0}/gold/{1}/".format(BUCKET, table), dataset=True)

        stories = gold("top_hn_stories_by_score").sort_values("rank")
        assert int(stories.iloc[0]["score"]) == 1200
        assert stories.iloc[0]["post_id"] == "p1"

        jobs = gold("top_hn_jobs_by_score").sort_values("rank")
        assert list(jobs["post_id"]) == ["p2", "p3"]

        followers = gold("top_x_users_by_followers").sort_values("rank")
        assert int(followers.iloc[0]["followers_count"]) == 1000000

        users_metric = gold("daily_users_metric")
        assert set(users_metric["platform"]) == {"Hacker News", "X"}

        dq = gold("data_quality_score")
        assert set(dq["source"]) == {"silver_users", "silver_posts"}

        item_counts = gold("daily_hn_item_counts")
        assert set(item_counts["post_type"]).issubset(set(metrics.HN_ITEM_TYPES))

    print("ok  - test_handler_s3_parquet_roundtrip")


def _run_all():
    if not HAVE_DEPS:
        print("SKIPPED (pandas/pyarrow/moto/awswrangler not installed)")
        return
    test_handler_s3_parquet_roundtrip()
    print("\n1 passed")


if __name__ == "__main__":
    _run_all()
