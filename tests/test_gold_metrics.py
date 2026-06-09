"""Unit tests for Marko's gold metric/KPI computation.

Pure Python, no AWS/pandas: the metrics work on lists of dicts, and the handler
dry-runs on the bundled sample silver dataset.

    pytest tests/test_gold_metrics.py
    python tests/test_gold_metrics.py
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "lambda", "gold")
sys.path.insert(0, SRC)

import handler  # noqa: E402
import metrics  # noqa: E402

USERS = [
    {"user_id": "h1", "username": "alice", "platform": "Hacker News", "karma_score": 25000, "is_verified": None, "followers_count": None, "created_at": "2026-01-15T08:00:00Z"},
    {"user_id": "h2", "username": "bob", "platform": "Hacker News", "karma_score": -12, "is_verified": None, "followers_count": None, "created_at": "2026-01-15T09:00:00Z"},
    {"user_id": "h3", "username": "carol", "platform": "Hacker News", "karma_score": 300, "is_verified": None, "followers_count": None, "created_at": "2026-01-16T09:00:00Z"},
    {"user_id": "x1", "username": "@nova", "platform": "X", "karma_score": None, "is_verified": True, "followers_count": 1000000, "created_at": "2026-01-15T10:00:00Z"},
    {"user_id": "x2", "username": "@pip", "platform": "X", "karma_score": None, "is_verified": False, "followers_count": 500, "created_at": "2026-01-16T10:00:00Z"},
]

POSTS = [
    {"post_id": "p1", "platform": "Hacker News", "author_username": "alice", "content_text": "story", "created_at": "2026-01-15T12:00:00Z", "post_type": "story", "score": 1200},
    {"post_id": "p2", "platform": "Hacker News", "author_username": "bob", "content_text": "job", "created_at": "2026-01-15T13:00:00Z", "post_type": "job", "score": 80},
    {"post_id": "p3", "platform": "Hacker News", "author_username": "bob", "content_text": "job2", "created_at": "2026-01-15T14:00:00Z", "post_type": "job", "score": 5},
    {"post_id": "p4", "platform": "Hacker News", "author_username": "alice", "content_text": "comment", "created_at": "2026-01-15T15:00:00Z", "post_type": "comment", "score": None},
    {"post_id": "p5", "platform": "Hacker News", "author_username": "carol", "content_text": "ask", "created_at": "2026-01-16T09:30:00Z", "post_type": "ask", "score": 40},
    {"post_id": "t1", "platform": "X", "author_username": "@nova", "content_text": "gm", "created_at": "2026-01-15T11:00:00Z", "post_type": "tweet", "score": None},
    {"post_id": "t2", "platform": "X", "author_username": "@pip", "content_text": "rt", "created_at": "2026-01-16T11:00:00Z", "post_type": "retweet", "score": None},
]

DATE = "2026-06-09"


def _find(rows, **match):
    for r in rows:
        if all(r.get(k) == v for k, v in match.items()):
            return r
    return None


def test_date_of_handles_iso_and_z():
    assert metrics.date_of("2026-01-15T21:54:18Z") == "2026-01-15"
    assert metrics.date_of("2026-01-15") == "2026-01-15"
    assert metrics.date_of(None) is None


def test_daily_hn_item_counts():
    rows = metrics.daily_hn_item_counts(POSTS)
    assert _find(rows, metric_date="2026-01-15", post_type="story")["item_count"] == 1
    assert _find(rows, metric_date="2026-01-15", post_type="job")["item_count"] == 2
    assert _find(rows, metric_date="2026-01-15", post_type="comment")["item_count"] == 1
    assert _find(rows, metric_date="2026-01-16", post_type="ask")["item_count"] == 1
    # X posts never appear in the HN item counts.
    assert all(r["post_type"] in metrics.HN_ITEM_TYPES for r in rows)


def test_daily_users_metric_hn():
    rows = metrics.daily_users_metric(USERS, POSTS)
    hn15 = _find(rows, metric_date="2026-01-15", platform="Hacker News")
    assert hn15["new_users"] == 2 and hn15["total_users"] == 2
    assert hn15["active_users"] == 2  # alice + bob posted
    assert hn15["post_count"] == 3 and hn15["comment_count"] == 1
    hn16 = _find(rows, metric_date="2026-01-16", platform="Hacker News")
    assert hn16["new_users"] == 1 and hn16["total_users"] == 3  # cumulative


def test_daily_users_metric_x():
    rows = metrics.daily_users_metric(USERS, POSTS)
    x16 = _find(rows, metric_date="2026-01-16", platform="X")
    assert x16["new_users"] == 1 and x16["total_users"] == 2


def test_top_x_users_by_followers():
    rows = metrics.top_x_users_by_followers(USERS, DATE)
    assert rows[0]["username"] == "@nova" and rows[0]["rank"] == 1
    assert rows[0]["followers_count"] == 1000000
    assert rows[1]["username"] == "@pip"
    # HN users (null followers) are excluded.
    assert all(r["followers_count"] is not None for r in rows)


def test_top_hn_users_by_karma_high_and_low():
    high = metrics.top_hn_users_by_karma_high(USERS, DATE)
    assert [r["username"] for r in high] == ["alice", "carol", "bob"]
    low = metrics.top_hn_users_by_karma_low(USERS, DATE)
    assert [r["username"] for r in low] == ["bob", "carol", "alice"]


def test_top_hn_jobs_and_stories_by_score():
    jobs = metrics.top_hn_jobs_by_score(POSTS, DATE)
    assert [r["post_id"] for r in jobs] == ["p2", "p3"]
    assert jobs[0]["score"] == 80
    stories = metrics.top_hn_stories_by_score(POSTS, DATE)
    assert stories[0]["post_id"] == "p1" and stories[0]["score"] == 1200


def test_top_n_caps_at_ten():
    many = [
        {"platform": "X", "username": "u{0}".format(i), "followers_count": i}
        for i in range(50)
    ]
    rows = metrics.top_x_users_by_followers(many, DATE)
    assert len(rows) == 10
    assert rows[0]["followers_count"] == 49  # highest first


def test_data_quality_score():
    good = metrics.data_quality_score(USERS, "silver_users", DATE, ("user_id", "username", "platform", "created_at"))
    assert good["total_records"] == 5 and good["valid_records"] == 5
    assert good["quality_score"] == 100.0

    dirty = [
        {"post_id": "a", "platform": "X", "created_at": "2026-01-15T00:00:00Z", "post_type": "tweet"},
        {"post_id": "b", "platform": "X", "created_at": None, "post_type": "tweet"},  # missing created_at
    ]
    dq = metrics.data_quality_score(dirty, "silver_posts", DATE, ("post_id", "platform", "created_at", "post_type"))
    assert dq["total_records"] == 2 and dq["valid_records"] == 1 and dq["invalid_records"] == 1
    assert dq["quality_score"] == 50.0


def test_compute_all_has_every_required_table():
    tables = metrics.compute_all(USERS, POSTS, DATE)
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
    assert set(tables) == expected
    assert set(tables) == set(metrics.PARTITION_COLS)  # every table has partitions defined


def test_handler_dry_run_on_bundled_sample():
    # Clean env-free dry run: no bucket, no local dirs -> bundled sample silver.
    saved = {k: os.environ.pop(k, None) for k in ("DATA_LAKE_BUCKET", "BRONZE_BUCKET", "SILVER_LOCAL_DIR", "GOLD_LOCAL_OUTPUT_DIR")}
    try:
        body = handler.lambda_handler({}, None)["body"]
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
    assert body["sink"] == "none"
    assert body["silver_source"] == "sample"
    assert body["input_counts"]["users"] == 7 and body["input_counts"]["posts"] == 8
    assert set(body["table_row_counts"]) == set(metrics.PARTITION_COLS)
    assert body["tables"]["top_hn_stories_by_score"][0]["score"] == 1200


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
