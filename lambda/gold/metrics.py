"""Gold-layer metric and KPI computation (Marko's slice).

Pure, dependency-free functions: silver records in (lists of dicts), gold metric
rows out (lists of dicts). No pandas, boto3, or awswrangler here, so every metric
is unit testable with plain Python. The handler does the Parquet/S3 I/O and calls
these.

Input is the normalized *silver* schema (see ``silver_contract.py``). Every
required metric/KPI from PROJECT_SPECIFICATION section 3 is produced:

  * daily HN item counts by type      -> daily_hn_item_counts
  * daily HN users / daily X users    -> daily_users_metric
  * top 10 X users by followers       -> top_x_users_by_followers
  * top 10 HN users by highest karma  -> top_hn_users_by_karma_high
  * top 10 HN users by lowest karma   -> top_hn_users_by_karma_low
  * top 10 HN jobs by score           -> top_hn_jobs_by_score
  * top 10 HN stories by score        -> top_hn_stories_by_score
  * Data Quality Score (KPI)          -> data_quality_score
"""

from __future__ import annotations

from datetime import datetime

from silver_contract import (
    PLATFORM_HN,
    PLATFORM_X,
    POSTS_REQUIRED_FIELDS,
    USERS_REQUIRED_FIELDS,
)

TOP_N = 10
HN_ITEM_TYPES = ("story", "ask", "comment", "job", "poll")


def date_of(ts):
    """Return the ``YYYY-MM-DD`` UTC date of an ISO-8601 timestamp, or None."""
    if not ts:
        return None
    s = str(ts)
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _is_hn(rec):
    return rec.get("platform") == PLATFORM_HN


def _is_x(rec):
    return rec.get("platform") == PLATFORM_X


# --- daily HN item counts -----------------------------------------------------

def daily_hn_item_counts(posts):
    """Daily counts of each HN item type (story/ask/comment/job/poll)."""
    counts = {}  # (date, type) -> n
    for p in posts:
        if not _is_hn(p):
            continue
        d = date_of(p.get("created_at"))
        t = p.get("post_type")
        if d is None or t is None:
            continue
        counts[(d, t)] = counts.get((d, t), 0) + 1
    rows = [
        {"metric_date": d, "post_type": t, "item_count": n}
        for (d, t), n in counts.items()
    ]
    rows.sort(key=lambda r: (r["metric_date"], r["post_type"]))
    return rows


# --- daily users per platform -------------------------------------------------

def daily_users_metric(users, posts):
    """Per (date, platform): new, cumulative-total, and active user counts.

    * new_users    -> users whose ``created_at`` date == that date
    * total_users  -> users whose ``created_at`` date <= that date (cumulative)
    * active_users -> distinct post authors on that date
    * post_count / comment_count -> posts that day (comments split out)
    """
    rows = []
    for platform in (PLATFORM_HN, PLATFORM_X):
        p_users = [u for u in users if u.get("platform") == platform]
        p_posts = [p for p in posts if p.get("platform") == platform]

        def cdate(u):
            return date_of(u.get("created_at"))

        user_dates = {cdate(u) for u in p_users if cdate(u)}
        post_dates = {date_of(p.get("created_at")) for p in p_posts if date_of(p.get("created_at"))}

        for d in sorted(user_dates | post_dates):
            new_users = sum(1 for u in p_users if cdate(u) == d)
            total_users = sum(1 for u in p_users if cdate(u) is not None and cdate(u) <= d)
            day_posts = [p for p in p_posts if date_of(p.get("created_at")) == d]
            active_users = len({p.get("author_username") for p in day_posts if p.get("author_username")})
            comment_count = sum(1 for p in day_posts if p.get("post_type") == "comment")
            post_count = len(day_posts) - comment_count
            rows.append({
                "metric_date": d,
                "platform": platform,
                "new_users": new_users,
                "total_users": total_users,
                "active_users": active_users,
                "post_count": post_count,
                "comment_count": comment_count,
            })
    rows.sort(key=lambda r: (r["platform"], r["metric_date"]))
    return rows


# --- top-N helpers ------------------------------------------------------------

def _ranked(records, key_field, metric_date, extra_fields, reverse=True, n=TOP_N):
    usable = [r for r in records if r.get(key_field) is not None]
    usable.sort(key=lambda r: r.get(key_field), reverse=reverse)
    out = []
    for i, r in enumerate(usable[:n], start=1):
        row = {"metric_date": metric_date, "rank": i, key_field: r.get(key_field)}
        for f in extra_fields:
            row[f] = r.get(f)
        out.append(row)
    return out


def top_x_users_by_followers(users, metric_date, n=TOP_N):
    x_users = [u for u in users if _is_x(u)]
    return _ranked(x_users, "followers_count", metric_date, ("username", "is_verified"), reverse=True, n=n)


def top_hn_users_by_karma_high(users, metric_date, n=TOP_N):
    hn = [u for u in users if _is_hn(u)]
    return _ranked(hn, "karma_score", metric_date, ("username",), reverse=True, n=n)


def top_hn_users_by_karma_low(users, metric_date, n=TOP_N):
    hn = [u for u in users if _is_hn(u)]
    return _ranked(hn, "karma_score", metric_date, ("username",), reverse=False, n=n)


def _top_hn_posts_by_score(posts, post_type, metric_date, n=TOP_N):
    subset = [p for p in posts if _is_hn(p) and p.get("post_type") == post_type]
    return _ranked(subset, "score", metric_date, ("post_id", "author_username", "content_text"), reverse=True, n=n)


def top_hn_jobs_by_score(posts, metric_date, n=TOP_N):
    return _top_hn_posts_by_score(posts, "job", metric_date, n)


def top_hn_stories_by_score(posts, metric_date, n=TOP_N):
    return _top_hn_posts_by_score(posts, "story", metric_date, n)


# --- KPI: Data Quality Score --------------------------------------------------

def data_quality_score(records, source, metric_date, required_fields):
    """Row-level DQ: a row is valid if every required field is present/non-empty.

    ``quality_score = valid_records / total_records * 100`` (0 when there are no
    records). Matches the data_quality_score PG table (total/valid/invalid/score).
    """
    total = len(records)
    valid = sum(1 for r in records if all(r.get(f) not in (None, "") for f in required_fields))
    invalid = total - valid
    score = round((valid / total) * 100, 2) if total else 0.0
    return {
        "metric_date": metric_date,
        "source": source,
        "total_records": total,
        "valid_records": valid,
        "invalid_records": invalid,
        "quality_score": score,
    }


# --- orchestration ------------------------------------------------------------

def compute_all(users, posts, metric_date):
    """Compute every gold table. Returns ``{table_name: list[dict]}``."""
    return {
        "daily_hn_item_counts": daily_hn_item_counts(posts),
        "daily_users_metric": daily_users_metric(users, posts),
        "top_x_users_by_followers": top_x_users_by_followers(users, metric_date),
        "top_hn_users_by_karma_high": top_hn_users_by_karma_high(users, metric_date),
        "top_hn_users_by_karma_low": top_hn_users_by_karma_low(users, metric_date),
        "top_hn_jobs_by_score": top_hn_jobs_by_score(posts, metric_date),
        "top_hn_stories_by_score": top_hn_stories_by_score(posts, metric_date),
        "data_quality_score": [
            data_quality_score(users, "silver_users", metric_date, USERS_REQUIRED_FIELDS),
            data_quality_score(posts, "silver_posts", metric_date, POSTS_REQUIRED_FIELDS),
        ],
    }


# Partition columns per gold table (used by the handler when writing Parquet).
PARTITION_COLS = {
    "daily_hn_item_counts": ["metric_date"],
    "daily_users_metric": ["platform", "metric_date"],
    "top_x_users_by_followers": ["metric_date"],
    "top_hn_users_by_karma_high": ["metric_date"],
    "top_hn_users_by_karma_low": ["metric_date"],
    "top_hn_jobs_by_score": ["metric_date"],
    "top_hn_stories_by_score": ["metric_date"],
    "data_quality_score": ["metric_date"],
}
