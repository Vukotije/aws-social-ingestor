"""Unit tests for the silver normalization slice (stdlib only, offline).

Exercises the pure normalization logic (``normalize.py``) and the handler's
local file-I/O mode (``handler.py``) entirely in-memory: no pandas, no boto3, no
network. HN user enrichment is driven through an injected fake ``fetch_json``.

    pytest tests/test_silver.py
    python3 tests/test_silver.py
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "lambda", "silver")
sys.path.insert(0, SRC)

import handler  # noqa: E402
import normalize  # noqa: E402

X_SAMPLE = os.path.join(HERE, "..", "lambda", "x", "dataset", "x_sample_tweets.jsonl")


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


# Raw Algolia-shaped HN hits (the subset of fields silver reads).
HN_STORY = {
    "objectID": "101",
    "author": "alice",
    "title": "Show HN: a tiny &amp; mighty <b>data lake</b>",
    "points": 1200,
    "created_at_i": 1748606400,  # 2025-05-30T12:00:00Z
    "created_at": "2025-05-30T12:00:00.000Z",
    "_tags": ["story", "author_alice", "story_101"],
}
HN_ASK = {
    "objectID": "102",
    "author": "bob",
    "title": "Ask HN: how do you test Lambdas?",
    "points": 42,
    "created_at_i": 1748610000,
    "_tags": ["story", "ask_hn", "author_bob"],
}
HN_COMMENT = {
    "objectID": "103",
    "author": "alice",
    "comment_text": "great <i>point</i>",
    "points": None,
    "created_at_i": 1748613600,
    "_tags": ["comment", "author_alice"],
}
HN_JOB = {
    "objectID": "104",
    "author": "carol",
    "title": "We are hiring",
    "points": 5,
    "created_at_i": 1748617200,
    "_tags": ["job", "author_carol"],
}
HN_HITS = [HN_STORY, HN_ASK, HN_COMMENT, HN_JOB]


def fake_hn_fetch(url):
    """Fake HN Firebase user endpoint: deterministic karma + created per username.

    Firebase user URLs end with ``<username>.json`` and the payload carries
    ``created`` as epoch seconds (converted to ISO by the normalizer).
    """
    leaf = url.rstrip("/").rsplit("/", 1)[-1]
    username = leaf[:-5] if leaf.endswith(".json") else leaf
    table = {
        "alice": {"id": "alice", "karma": 25000, "created": 1420070400},  # 2015-01-01Z
        "bob": {"id": "bob", "karma": 300, "created": 1527811200},        # 2018-06-01Z
        "carol": {"id": "carol", "karma": 17, "created": 1580601600},     # 2020-02-02Z
    }
    return table[username]


# --- HN post normalization ------------------------------------------------


def test_hn_post_type_priority():
    assert normalize.hn_post_type(["comment", "story"]) == "comment"
    assert normalize.hn_post_type(["story", "ask_hn"]) == "ask"
    assert normalize.hn_post_type(["story"]) == "story"
    assert normalize.hn_post_type(["job"]) == "job"
    assert normalize.hn_post_type(["poll"]) == "poll"
    assert normalize.hn_post_type(["author_x"]) is None


def test_hn_post_normalization_fields():
    row = normalize.normalize_hn_post(HN_STORY)
    assert row["post_id"] == "101"
    assert row["platform"] == "Hacker News"
    assert row["author_username"] == "alice"
    # HTML stripped + entities unescaped.
    assert row["content_text"] == "Show HN: a tiny & mighty data lake"
    # epoch -> ISO Z, no fractional seconds.
    assert row["created_at"] == "2025-05-30T12:00:00Z"
    assert row["post_type"] == "story"
    assert row["score"] == 1200
    assert list(row.keys()) == list(normalize.POSTS_FIELDS)


def test_hn_post_null_points_and_content_fallback():
    row = normalize.normalize_hn_post(HN_COMMENT)
    assert row["score"] is None
    assert row["post_type"] == "comment"
    assert row["content_text"] == "great point"  # falls back to comment_text


def test_hn_post_created_at_fallback_when_no_epoch():
    hit = dict(HN_STORY)
    hit.pop("created_at_i")
    row = normalize.normalize_hn_post(hit)
    assert row["created_at"] == "2025-05-30T12:00:00.000Z"  # raw ISO fallback


# --- HN user dedup + enrichment ------------------------------------------


def test_hn_users_dedup_and_enrichment():
    posts = [normalize.normalize_hn_post(h) for h in HN_HITS]
    users = normalize.normalize_hn_users(posts, fetch_json=fake_hn_fetch, enrich=True)
    # alice appears twice (story + comment) -> one row; first-seen order.
    assert [u["username"] for u in users] == ["alice", "bob", "carol"]
    alice = users[0]
    assert alice["user_id"] == "alice"
    assert alice["karma_score"] == 25000
    assert alice["created_at"] == "2015-01-01T00:00:00Z"
    assert alice["platform"] == "Hacker News"
    assert alice["is_verified"] is None
    assert alice["followers_count"] is None
    assert list(alice.keys()) == list(normalize.USERS_FIELDS)


def test_hn_users_enrich_disabled():
    posts = [normalize.normalize_hn_post(h) for h in HN_HITS]
    users = normalize.normalize_hn_users(posts, fetch_json=fake_hn_fetch, enrich=False)
    for u in users:
        assert u["karma_score"] is None
        assert u["created_at"] is None


def test_hn_users_enrich_limit_honored():
    posts = [normalize.normalize_hn_post(h) for h in HN_HITS]
    users = normalize.normalize_hn_users(
        posts, fetch_json=fake_hn_fetch, enrich=True, enrich_limit=1
    )
    # only the first distinct author (alice) enriched; the rest stay None.
    assert users[0]["karma_score"] == 25000
    assert users[1]["karma_score"] is None
    assert users[2]["karma_score"] is None


def test_hn_users_fetch_error_swallowed():
    def boom(url):
        raise RuntimeError("network down")

    posts = [normalize.normalize_hn_post(h) for h in HN_HITS]
    users = normalize.normalize_hn_users(posts, fetch_json=boom, enrich=True)
    for u in users:
        assert u["karma_score"] is None
        assert u["created_at"] is None


# --- X normalization ------------------------------------------------------


def test_x_post_tweet_vs_retweet():
    tweets = _read_jsonl(X_SAMPLE)
    rows = [normalize.normalize_x_post(t) for t in tweets]
    elon = rows[0]
    assert elon["post_id"] == "1879500000000000001"
    assert elon["platform"] == "X"
    assert elon["author_username"] == "elonmusk"
    assert elon["post_type"] == "tweet"
    assert elon["score"] is None
    assert list(elon.keys()) == list(normalize.POSTS_FIELDS)
    retweets = [r for r in rows if r["post_type"] == "retweet"]
    assert retweets, "expected at least one retweet in the sample"


def test_x_user_verified_and_followers_and_dedup():
    tweets = _read_jsonl(X_SAMPLE)
    users = normalize.normalize_x_users(tweets)
    by_username = {u["username"]: u for u in users}
    elon = by_username["elonmusk"]
    assert elon["user_id"] == "44196397"
    assert elon["is_verified"] is True
    assert elon["followers_count"] == 181000000
    assert elon["karma_score"] is None
    assert list(elon.keys()) == list(normalize.USERS_FIELDS)
    # distinct user.id -> no duplicate user rows.
    ids = [u["user_id"] for u in users]
    assert len(ids) == len(set(ids))


# --- top-level normalize() ------------------------------------------------


def test_normalize_combines_both_sources():
    tweets = _read_jsonl(X_SAMPLE)
    users, posts = normalize.normalize(
        HN_HITS, tweets, fetch_json=fake_hn_fetch, enrich=True
    )
    platforms_u = {u["platform"] for u in users}
    platforms_p = {p["platform"] for p in posts}
    assert platforms_u == {"Hacker News", "X"}
    assert platforms_p == {"Hacker News", "X"}
    assert len(posts) == len(HN_HITS) + len(tweets)


# --- handler local mode end-to-end ---------------------------------------


def _write_bronze_fixture(root, ingestion_date):
    hn_key = os.path.join(
        root, "bronze", "hacker_news", "ingestion_date=" + ingestion_date, "raw_items.jsonl"
    )
    x_key = os.path.join(
        root, "bronze", "x", "ingestion_date=" + ingestion_date, "raw_dataset.jsonl"
    )
    os.makedirs(os.path.dirname(hn_key), exist_ok=True)
    os.makedirs(os.path.dirname(x_key), exist_ok=True)
    with open(hn_key, "w", encoding="utf-8") as fh:
        for hit in HN_HITS:
            fh.write(json.dumps(hit) + "\n")
    # Reuse the real X sample as the X bronze fixture.
    with open(X_SAMPLE, "rb") as src, open(x_key, "wb") as dst:
        dst.write(src.read())


def test_handler_local_mode_produces_silver_jsonl():
    ingestion_date = "2026-05-30"
    tweets = _read_jsonl(X_SAMPLE)
    with tempfile.TemporaryDirectory() as bronze_dir, tempfile.TemporaryDirectory() as silver_dir:
        _write_bronze_fixture(bronze_dir, ingestion_date)
        with env(
            DATA_LAKE_BUCKET=None,
            BRONZE_BUCKET=None,
            BRONZE_LOCAL_DIR=bronze_dir,
            SILVER_LOCAL_OUTPUT_DIR=silver_dir,
            HN_ENRICH_USERS="0",
            INGESTION_DATE=ingestion_date,
        ):
            body = handler.lambda_handler({}, None)["body"]

        assert body["sink"] == "local"
        assert body["source"].startswith("local:")
        assert body["input_counts"] == {"hn": len(HN_HITS), "x": len(tweets)}

        users = _read_jsonl(os.path.join(silver_dir, "users.jsonl"))
        posts = _read_jsonl(os.path.join(silver_dir, "posts.jsonl"))

        # 3 distinct HN authors + distinct X users.
        x_user_ids = {str(t["user"]["id"]) for t in tweets}
        assert len(users) == 3 + len(x_user_ids)
        assert len(posts) == len(HN_HITS) + len(tweets)
        assert body["output_counts"] == {"users": len(users), "posts": len(posts)}

        # Schema keys match the contract, in order.
        for u in users:
            assert list(u.keys()) == list(normalize.USERS_FIELDS)
        for p in posts:
            assert list(p.keys()) == list(normalize.POSTS_FIELDS)

        # Enrichment disabled -> HN karma is null.
        hn_users = [u for u in users if u["platform"] == "Hacker News"]
        assert all(u["karma_score"] is None for u in hn_users)


def test_handler_dry_run_writes_nothing():
    with env(
        DATA_LAKE_BUCKET=None,
        BRONZE_BUCKET=None,
        BRONZE_LOCAL_DIR=None,
        SILVER_LOCAL_OUTPUT_DIR=None,
    ):
        body = handler.lambda_handler({}, None)["body"]
    assert body["sink"] == "none"
    assert body["written"] is None
    assert body["output_counts"] == {"users": 0, "posts": 0}


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
