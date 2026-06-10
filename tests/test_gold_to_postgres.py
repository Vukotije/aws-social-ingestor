from __future__ import annotations

import contextlib
import datetime
import json
import os
import sys
import tempfile


HERE = os.path.dirname(os.path.abspath(__file__))
LOADER_SRC = os.path.join(HERE, "..", "lambda", "gold_to_postgres")
sys.path.insert(0, LOADER_SRC)

import handler  # noqa: E402
import loader  # noqa: E402


@contextlib.contextmanager
def env(**overrides):
    saved = {key: os.environ.get(key) for key in overrides}
    try:
        for key, value in overrides.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_missing_env_returns_400():
    with env(DATA_LAKE_BUCKET=None, GOLD_PREFIX=None, POSTGRES_PASSWORD_SECRET_ARN=None):
        result = handler.lambda_handler({}, None)

    assert result["statusCode"] == 400
    assert result["body"]["loaded"] is False
    assert "DATA_LAKE_BUCKET" in result["body"]["missing"]


def test_build_load_plan_uses_event_and_env():
    with env(
        DATA_LAKE_BUCKET="bucket",
        GOLD_PREFIX="gold",
        POSTGRES_PASSWORD_SECRET_ARN="secret-arn",
        POSTGRES_HOST="postgres.internal",
        POSTGRES_DB="metrics",
        POSTGRES_USER="loader",
        TARGET_DATE="2026-05-31",
    ):
        result = handler.lambda_handler(
            {"metric_tables": ["daily_users_metric", "data_quality_score"]},
            None,
        )

    body = result["body"]
    assert result["statusCode"] == 200
    assert body["mode"] == "dry_run"
    assert body["plan"]["bucket"] == "bucket"
    assert body["plan"]["metric_tables"] == ["daily_users_metric", "data_quality_score"]
    assert body["plan"]["target_date"] == "2026-05-31"


def test_build_upsert_sql_has_conflict_and_excluded():
    sql = loader.build_upsert_sql("top_hn_stories_by_score")
    assert "INSERT INTO top_hn_stories_by_score" in sql
    assert "ON CONFLICT (metric_date, rank)" in sql
    assert "DO UPDATE SET" in sql
    assert "score = EXCLUDED.score" in sql
    # PK columns must not appear in the SET clause.
    set_clause = sql.split("DO UPDATE SET", 1)[1]
    assert "metric_date = EXCLUDED.metric_date" not in set_clause
    assert "rank = EXCLUDED.rank" not in set_clause


def test_prepare_rows_orders_and_coerces():
    cols = loader.TABLE_SPECS["top_hn_stories_by_score"]["cols"]
    raw = [
        {
            "metric_date": datetime.datetime(2026, 5, 31, 12, 0, 0),
            "rank": 1,
            "post_id": "p1",
            "score": 42,
            # author_username + content_text intentionally missing
            "extra_unused": "drop me",
        }
    ]
    rows = loader.prepare_rows("top_hn_stories_by_score", raw)
    assert len(rows) == 1
    row = rows[0]
    assert len(row) == len(cols)
    # tuple order matches the declared column order
    assert row[cols.index("metric_date")] == "2026-05-31"
    assert isinstance(row[cols.index("metric_date")], str)
    assert row[cols.index("rank")] == 1
    assert row[cols.index("post_id")] == "p1"
    assert row[cols.index("score")] == 42
    # missing keys default to None; extras are dropped
    assert row[cols.index("author_username")] is None
    assert row[cols.index("content_text")] is None


def test_default_tables_is_all_eight():
    assert handler.metric_tables_from_event({}) == []
    assert len(loader.ALL_TABLES) == 8
    expected = {
        "daily_hn_item_counts",
        "daily_users_metric",
        "top_x_users_by_followers",
        "top_hn_users_by_karma_high",
        "top_hn_users_by_karma_low",
        "top_hn_jobs_by_score",
        "top_hn_stories_by_score",
        "data_quality_score",
    }
    assert set(loader.ALL_TABLES) == expected
    assert set(loader.TABLE_SPECS) == expected


def test_execute_path_upserts_with_fake_conn():
    captured = {}

    def fake_execute_values(cur, sql, rows):
        captured["sql"] = sql
        captured["rows"] = rows

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeConn:
        def cursor(self):
            return FakeCursor()

    table = "daily_users_metric"
    gold_rows = [
        {
            "metric_date": "2026-05-31",
            "platform": "hackernews",
            "new_users": 3,
            "total_users": 10,
            "active_users": 2,
            "post_count": 5,
            "comment_count": 1,
        }
    ]

    with tempfile.TemporaryDirectory() as tmp:
        dest = os.path.join(tmp, "gold", table)
        os.makedirs(dest)
        with open(os.path.join(dest, "data.json"), "w", encoding="utf-8") as handle:
            json.dump(gold_rows, handle)

        rows = loader.read_gold_table_local(tmp, "gold", table)
        prepared = loader.prepare_rows(table, rows)
        n = loader.upsert_rows(FakeConn(), table, prepared, execute_values=fake_execute_values)

    assert n == 1
    assert "INSERT INTO daily_users_metric" in captured["sql"]
    cols = loader.TABLE_SPECS[table]["cols"]
    assert captured["rows"] == [
        (
            "2026-05-31", "hackernews", 3, 10, 2, 5, 1,
        )
    ]
    assert len(captured["rows"][0]) == len(cols)


def _run_all():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print("ok  - {0}".format(test.__name__))
    print("\n{0} passed".format(len(tests)))


if __name__ == "__main__":
    _run_all()
