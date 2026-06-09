"""The silver schema the gold layer reads (Marko's assumption of Vukan's output).

Vukan's silver slice owns the real normalization; this file documents the exact
shape the gold metrics depend on, so the two can be frozen together before gold
relies on them (Integration Milestone #1 in FULL_IMPLEMENTATION_PLAN.md). If
silver settles on different column names, update this one file and the metrics
keep working.
"""

from __future__ import annotations

PLATFORM_HN = "Hacker News"
PLATFORM_X = "X"

# silver `users` (one row per user per platform).
USERS_FIELDS = (
    "user_id",          # stable id (uuid or source id)
    "username",         # display name / handle
    "platform",         # "Hacker News" | "X"
    "karma_score",      # int, HN only (null for X)
    "is_verified",      # bool, X only (null for HN)
    "followers_count",  # int, X only (null for HN) — needed for top-X-by-followers
    "created_at",       # ISO-8601 UTC
)

# silver `posts` (one row per story/ask/comment/job/poll/tweet/retweet).
POSTS_FIELDS = (
    "post_id",
    "platform",         # "Hacker News" | "X"
    "author_username",
    "content_text",
    "created_at",       # ISO-8601 UTC
    "post_type",        # story|ask|comment|job|poll|tweet|retweet
    "score",            # int, HN (null where not applicable) — needed for top-by-score
)

# Fields that must be present/non-empty for a row to count as "valid" in the
# Data Quality Score KPI. Kept to the identifying + typing columns so the score
# reflects normalization completeness rather than optional data being sparse.
USERS_REQUIRED_FIELDS = ("user_id", "username", "platform", "created_at")
POSTS_REQUIRED_FIELDS = ("post_id", "platform", "created_at", "post_type")
