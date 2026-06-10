"""Silver-layer normalization logic (Vukan's slice).

Turns the raw bronze hits from each source (Hacker News Algolia hits and X
tweets) into the two normalized silver datasets the gold layer reads:
``users`` and ``posts``. The exact output schema is frozen in
``lambda/gold/silver_contract.py`` (Integration Milestone #1); this module
produces rows whose keys match it, in contract order.

All the logic here is pure so it can be unit tested locally without AWS, pandas,
or the network. The only outbound dependency — enriching HN users with their
karma and account-creation date from the Hacker News Firebase user endpoint — is
isolated behind an injectable ``fetch_json`` (the same network-isolation pattern
as ``hn_ingest.fetch_json``), so every helper can be exercised with in-memory
fixtures.
"""

from __future__ import annotations

from datetime import datetime, timezone
import html
import json
import re
from urllib.request import Request, urlopen

# Platform identity. silver_contract.py owns the canonical PLATFORM_HN/PLATFORM_X
# constants, but it lives under lambda/gold/ and Lambda packages ship one dir
# each, so we deliberately hardcode the two strings here (kept byte-for-byte
# identical) rather than importing across lambda dirs.
PLATFORM_HN = "Hacker News"
PLATFORM_X = "X"

# Contract column order (must mirror silver_contract.USERS_FIELDS / POSTS_FIELDS).
USERS_FIELDS = (
    "user_id",
    "username",
    "platform",
    "karma_score",
    "is_verified",
    "followers_count",
    "created_at",
)
POSTS_FIELDS = (
    "post_id",
    "platform",
    "author_username",
    "content_text",
    "created_at",
    "post_type",
    "score",
)

# Default cap on how many distinct HN users to enrich with karma (one HTTP call
# each). "0" / None means unlimited.
DEFAULT_ENRICH_LIMIT = 200

# The HN Firebase v0 user endpoint returns BOTH karma and the account-creation
# time (`created`, epoch seconds) in one call — unlike the Algolia users endpoint,
# which omits the creation date — so it populates karma_score AND created_at.
HN_USER_API = "https://hacker-news.firebaseio.com/v0/user/{username}.json"

_TAG_RE = re.compile(r"<[^>]+>")


def fetch_json(url, timeout=30) -> dict:
    """Fetch and decode a JSON document over HTTP (stdlib only).

    Isolated here so callers can inject a fake fetcher in tests, mirroring
    ``hn_ingest.fetch_json``. ``boto3``-free and ``requests``-free so the Lambda
    needs no extra dependencies for user enrichment.
    """
    request = Request(url, headers={"User-Agent": "aws-social-ingestor-silver/1.0"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - trusted HN host
        return json.loads(response.read().decode("utf-8"))


def strip_html(text) -> str:
    """Strip HTML tags and unescape entities; return "" for falsy input."""
    if not text:
        return ""
    return html.unescape(_TAG_RE.sub("", str(text))).strip()


def _epoch_to_iso(created_at_i) -> str:
    """Format a UTC epoch (seconds) as ``2026-05-30T12:00:00Z``."""
    dt = datetime.fromtimestamp(int(created_at_i), tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# --- Hacker News ----------------------------------------------------------


def hn_post_type(tags) -> str | None:
    """Derive the spec ``post_type`` from a hit's raw Algolia ``_tags``.

    Priority order matters: comments/jobs/polls are leaf types; an Ask HN post
    carries both ``story`` and ``ask_hn`` so ``ask`` is checked before ``story``.
    """
    tags = tags or []
    if "comment" in tags:
        return "comment"
    if "job" in tags:
        return "job"
    if "poll" in tags:
        return "poll"
    if "ask_hn" in tags:
        return "ask"
    if "story" in tags:
        return "story"
    return None


def normalize_hn_post(hit) -> dict:
    """Normalize a single raw Algolia hit into a silver ``posts`` row."""
    content = strip_html(
        hit.get("title") or hit.get("story_text") or hit.get("comment_text") or ""
    )

    created_at_i = hit.get("created_at_i")
    if created_at_i is not None:
        created_at = _epoch_to_iso(created_at_i)
    else:
        created_at = hit.get("created_at")

    points = hit.get("points")
    score = int(points) if points is not None else None

    return {
        "post_id": str(hit.get("objectID")),
        "platform": PLATFORM_HN,
        "author_username": hit.get("author"),
        "content_text": content,
        "created_at": created_at,
        "post_type": hn_post_type(hit.get("_tags")),
        "score": score,
    }


def _enrich_hn_user(username, fetch_json) -> tuple:
    """Return ``(karma_score, created_at)`` for an HN user, swallowing errors.

    Any network/parse failure yields ``(None, None)`` so one bad user never
    crashes the whole run.
    """
    try:
        payload = fetch_json(HN_USER_API.format(username=username))
    except Exception:  # noqa: BLE001 - enrichment is best-effort, per spec
        return None, None
    if not isinstance(payload, dict):
        return None, None
    karma = payload.get("karma")
    karma = int(karma) if karma is not None else None
    created = payload.get("created")  # Firebase: account-creation epoch seconds
    created_at = _epoch_to_iso(created) if created is not None else None
    return karma, created_at


def normalize_hn_users(posts, fetch_json, enrich=True, enrich_limit=DEFAULT_ENRICH_LIMIT) -> list:
    """Build silver ``users`` rows from HN posts (one per distinct author).

    Authors are deduplicated in first-seen order. When ``enrich`` is true the
    first ``enrich_limit`` distinct authors are looked up on the HN Firebase user
    endpoint for karma + account-creation date; the rest (and any lookup that
    errors) get ``karma_score`` / ``created_at`` of ``None``. ``enrich_limit``
    of 0 (or falsy) means unlimited.
    """
    seen = []
    seen_set = set()
    for post in posts:
        author = post.get("author_username")
        if author and author not in seen_set:
            seen_set.add(author)
            seen.append(author)

    limit = enrich_limit or 0  # 0 -> unlimited
    rows = []
    for index, username in enumerate(seen):
        karma = None
        created_at = None
        within_limit = limit == 0 or index < limit
        if enrich and within_limit:
            karma, created_at = _enrich_hn_user(username, fetch_json)
        rows.append(
            {
                "user_id": username,  # HN's stable handle is its id
                "username": username,
                "platform": PLATFORM_HN,
                "karma_score": karma,
                "is_verified": None,
                "followers_count": None,
                "created_at": created_at,
            }
        )
    return rows


# --- X --------------------------------------------------------------------


def normalize_x_post(tweet) -> dict:
    """Normalize a single raw tweet into a silver ``posts`` row."""
    user = tweet.get("user") or {}
    return {
        "post_id": str(tweet.get("id")),
        "platform": PLATFORM_X,
        "author_username": user.get("username"),
        "content_text": strip_html(tweet.get("text")),
        "created_at": tweet.get("created_at"),
        "post_type": "retweet" if tweet.get("is_retweet") else "tweet",
        "score": None,
    }


def normalize_x_users(tweets) -> list:
    """Build silver ``users`` rows from tweets (one per distinct ``user.id``)."""
    seen = set()
    rows = []
    for tweet in tweets:
        user = tweet.get("user") or {}
        user_id = user.get("id")
        if user_id is None:
            continue
        user_id = str(user_id)
        if user_id in seen:
            continue
        seen.add(user_id)
        followers = user.get("followers_count")
        rows.append(
            {
                "user_id": user_id,
                "username": user.get("username"),
                "platform": PLATFORM_X,
                "karma_score": None,
                "is_verified": bool(user.get("verified")),
                "followers_count": int(followers) if followers is not None else None,
                "created_at": user.get("created_at"),
            }
        )
    return rows


# --- top level ------------------------------------------------------------


def normalize(
    hn_raw_hits,
    x_raw_tweets,
    fetch_json=fetch_json,
    enrich=True,
    enrich_limit=DEFAULT_ENRICH_LIMIT,
) -> tuple:
    """Normalize both bronze sources into ``(users, posts)`` silver rows.

    ``users`` = HN users + X users; ``posts`` = HN posts + X posts. ``fetch_json``
    is injectable so the (only) network dependency — HN karma enrichment — can be
    faked offline in tests.
    """
    hn_raw_hits = hn_raw_hits or []
    x_raw_tweets = x_raw_tweets or []

    hn_posts = [normalize_hn_post(hit) for hit in hn_raw_hits]
    hn_users = normalize_hn_users(
        hn_posts, fetch_json=fetch_json, enrich=enrich, enrich_limit=enrich_limit
    )

    x_posts = [normalize_x_post(tweet) for tweet in x_raw_tweets]
    x_users = normalize_x_users(x_raw_tweets)

    users = hn_users + x_users
    posts = hn_posts + x_posts
    return users, posts
