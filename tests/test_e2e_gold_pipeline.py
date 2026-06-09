"""End-to-end test for the gold pipeline: silver files -> handler -> gold files.

Runs the real handler load -> compute -> write -> reload cycle against the
bundled sample silver dataset, writing every gold table to a temp dir and
validating the results. Pure stdlib (offline local sink); runnable with or
without pytest.

    pytest tests/test_e2e_gold_pipeline.py
    python tests/test_e2e_gold_pipeline.py
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "lambda", "gold")
sys.path.insert(0, SRC)

import handler  # noqa: E402
import metrics  # noqa: E402

SAMPLE_SILVER = os.path.join(SRC, "sample_silver")


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


def _run_pipeline(out_dir):
    with env(
        DATA_LAKE_BUCKET=None,
        BRONZE_BUCKET=None,
        SILVER_LOCAL_DIR=SAMPLE_SILVER,
        GOLD_LOCAL_OUTPUT_DIR=out_dir,
        INGESTION_DATE="2026-01-16",
    ):
        return handler.lambda_handler({}, None)["body"]


def _load_table(out_dir, name):
    with open(os.path.join(out_dir, "gold", name, "data.json")) as fh:
        return json.load(fh)


def test_e2e_writes_every_gold_table_as_files():
    with tempfile.TemporaryDirectory() as out:
        body = _run_pipeline(out)
        assert body["sink"] == "local"
        assert body["silver_source"].startswith("local:")
        for name in metrics.PARTITION_COLS:
            path = os.path.join(out, "gold", name, "data.json")
            assert os.path.isfile(path), "missing gold table file: {0}".format(name)
            # Reload and confirm the on-disk row count matches what the run reported.
            assert len(_load_table(out, name)) == body["table_row_counts"][name]


def test_e2e_metric_values_are_correct():
    with tempfile.TemporaryDirectory() as out:
        _run_pipeline(out)

        stories = _load_table(out, "top_hn_stories_by_score")
        assert stories[0]["post_id"] == "p1" and stories[0]["score"] == 1200
        assert stories[0]["rank"] == 1

        jobs = _load_table(out, "top_hn_jobs_by_score")
        assert [j["post_id"] for j in jobs] == ["p2", "p3"]

        followers = _load_table(out, "top_x_users_by_followers")
        assert followers[0]["username"] == "@nova"
        assert followers[0]["followers_count"] == 1000000

        # Daily users metric covers both platforms.
        platforms = {r["platform"] for r in _load_table(out, "daily_users_metric")}
        assert platforms == {"Hacker News", "X"}

        # Data Quality Score: one row per silver source, score present and in range.
        dq = _load_table(out, "data_quality_score")
        sources = {r["source"] for r in dq}
        assert sources == {"silver_users", "silver_posts"}
        for row in dq:
            assert 0.0 <= row["quality_score"] <= 100.0


def test_e2e_hn_item_counts_only_hn_types():
    with tempfile.TemporaryDirectory() as out:
        _run_pipeline(out)
        rows = _load_table(out, "daily_hn_item_counts")
        assert rows, "expected HN item counts"
        for row in rows:
            assert row["post_type"] in metrics.HN_ITEM_TYPES


def _run_all():
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for func in funcs:
        func()
        passed += 1
        print("ok  - {0}".format(func.__name__))
    print("\n{0} passed".format(passed))


if __name__ == "__main__":
    _run_all()
