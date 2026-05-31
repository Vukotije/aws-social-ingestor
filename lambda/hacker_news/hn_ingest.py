"""Bronze-layer ingestion logic for the Hacker News source.

This module holds the pure logic so it can be unit tested locally without AWS
credentials. Network access is isolated behind ``fetch_json`` (and is fully
injectable), so every helper here can be exercised with in-memory fixtures.

Source: the Hacker News Search API (Algolia), ``search_by_date`` endpoint. It
is used instead of the official Firebase ``v0`` API because:

  * The five spec types (``story``, ``ask``, ``comment``, ``job``, ``poll``)
    map directly onto Algolia tags (``ask_hn`` -> ``ask``); the Firebase API has
    no ``ask`` type (Ask HN posts are just stories).
  * "Items created the previous day" is a single date-range query
    (``numericFilters=created_at_i>=START,created_at_i<END``) instead of walking
    tens of thousands of item ids.

Bronze-layer rule: hits are stored in S3 exactly as the API returns them, one
JSON object per line. Nothing here cleans HTML, normalizes timestamps (the raw
epoch ``created_at_i`` is preserved for the later silver layer), flattens nested
fields, maps schemas, or deduplicates. ``count_by_type`` only *reads* each hit's
``_tags`` to report counts for metadata; the stored objects are never mutated.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# --- Source identity / provenance (see lambda/hacker_news/README.md) ---
SOURCE_NAME = "hacker-news"
ALGOLIA_BASE_URL = "https://hn.algolia.com/api/v1/search_by_date"

# Spec types, in the order they are reported in metadata.
ITEM_TYPES = ("story", "ask", "comment", "job", "poll")

# Algolia ``_tags`` that identify each spec type. ``ask`` is a sub-tag of story
# (an Ask HN post is tagged both ``story`` and ``ask_hn``), so it is counted as a
# subset rather than fetched separately (which would create duplicate raw rows).
TYPE_TAGS = {
    "story": "story",
    "ask": "ask_hn",
    "comment": "comment",
    "job": "job",
    "poll": "poll",
}

# Tags fetched in the single daily query. ``ask_hn`` items come back via the
# ``story`` tag, so it is intentionally absent here: each item is returned once.
QUERY_TAGS = ("story", "comment", "poll", "job")

# Object names written to S3 (shared bronze contract).
RAW_OBJECT_NAME = "raw_items.jsonl"

# Algolia caps ``hitsPerPage`` at 1000.
MAX_HITS_PER_PAGE = 1000
DEFAULT_HITS_PER_PAGE = 1000
# Defensive cap so a misbehaving API response can never spin forever.
MAX_PAGES = 1000
# Algolia only lets you *reach* the first ~1000 results of any single query
# (``paginationLimitedTo``). A busy HN day has many thousands of comments, so a
# whole-day query would silently drop everything past the 1000th item. To stay
# complete we recursively split the day into smaller time windows until each
# window's total (``nbHits``) fits under this reachable limit.
PAGINATION_LIMIT = 1000


def bronze_prefix(env=None) -> str:
    """Return the bronze prefix from the environment (defaults to ``bronze``)."""
    env = os.environ if env is None else env
    return env.get("BRONZE_PREFIX", "bronze").strip("/")


def resolve_ingestion_date(env=None, today=None) -> str:
    """Resolve the ingestion date as ``YYYY-MM-DD``.

    Honors the shared ``INGESTION_DATE`` override used for testing; otherwise
    uses the current UTC date. ``today`` is injectable so callers/tests stay
    deterministic.
    """
    env = os.environ if env is None else env
    override = env.get("INGESTION_DATE")
    if override:
        return override.strip()
    if today is None:
        today = datetime.now(timezone.utc).date()
    return today.isoformat()


def resolve_target_date(env=None, ingestion_date=None) -> str:
    """Resolve the source-data date (the day whose items we collect).

    Honors the shared ``TARGET_DATE`` override; otherwise defaults to the day
    before ``ingestion_date`` (the spec collects "items created the previous
    day").
    """
    env = os.environ if env is None else env
    override = env.get("TARGET_DATE")
    if override:
        return override.strip()
    if ingestion_date is None:
        ingestion_date = resolve_ingestion_date(env)
    day = datetime.strptime(ingestion_date, "%Y-%m-%d").date()
    return (day - timedelta(days=1)).isoformat()


def build_object_keys(ingestion_date, prefix="bronze") -> dict:
    """Build the shared-contract S3 keys for the Hacker News bronze output.

    Layout:
        <prefix>/hacker_news/ingestion_date=YYYY-MM-DD/raw_items.jsonl
        <prefix>/hacker_news/ingestion_date=YYYY-MM-DD/metadata.json
    """
    base = "{prefix}/hacker_news/ingestion_date={date}".format(
        prefix=prefix.strip("/"), date=ingestion_date
    )
    return {
        "base": base,
        "raw_key": "{base}/{name}".format(base=base, name=RAW_OBJECT_NAME),
        "metadata_key": "{base}/metadata.json".format(base=base),
    }


def day_epoch_bounds(target_date) -> tuple:
    """Return ``(start, end)`` UTC epoch seconds for the given ``YYYY-MM-DD``.

    ``start`` is inclusive (00:00:00 UTC of ``target_date``); ``end`` is
    exclusive (00:00:00 UTC of the next day). Used to build the Algolia
    ``numericFilters`` range and as a client-side guard.
    """
    day = datetime.strptime(target_date, "%Y-%m-%d").date()
    start_dt = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    end_dt = start_dt + timedelta(days=1)
    return int(start_dt.timestamp()), int(end_dt.timestamp())


def search_url(start, end, page=0, hits_per_page=DEFAULT_HITS_PER_PAGE, tags=QUERY_TAGS) -> str:
    """Build an Algolia ``search_by_date`` URL for one page of a day's items."""
    hits_per_page = min(int(hits_per_page), MAX_HITS_PER_PAGE)
    tags_expr = "({0})".format(",".join(tags))
    query = urlencode(
        {
            "tags": tags_expr,
            "numericFilters": "created_at_i>={start},created_at_i<{end}".format(
                start=int(start), end=int(end)
            ),
            "page": int(page),
            "hitsPerPage": hits_per_page,
        }
    )
    return "{base}?{query}".format(base=ALGOLIA_BASE_URL, query=query)


def fetch_json(url, timeout=30) -> dict:
    """Fetch and decode a JSON document over HTTP (stdlib only).

    Isolated here so callers can inject a fake fetcher in tests. ``boto3``-free
    and ``requests``-free so the Lambda needs no extra dependencies.
    """
    request = Request(url, headers={"User-Agent": "aws-social-ingestor-bronze/1.0"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - trusted HN host
        return json.loads(response.read().decode("utf-8"))


def _fetch_window(start, end, fetcher, hits_per_page) -> list:
    """Collect every hit in the half-open ``[start, end)`` epoch window.

    If the window holds more matches than Algolia will page through
    (``PAGINATION_LIMIT``), it is split in half by time and each half is fetched
    recursively, so no items are lost. Sub-windows are disjoint, so no item is
    fetched twice.
    """
    first = fetcher(search_url(start, end, page=0, hits_per_page=hits_per_page))
    page_hits = first.get("hits", []) or []
    nb_hits = first.get("nbHits")
    if nb_hits is None:
        nb_hits = len(page_hits)

    # Too many matches to page through, and the window is still splittable.
    if int(nb_hits) > PAGINATION_LIMIT and (end - start) > 1:
        mid = start + (end - start) // 2
        return _fetch_window(start, mid, fetcher, hits_per_page) + _fetch_window(
            mid, end, fetcher, hits_per_page
        )

    # Reachable window: page through whatever is here.
    hits = list(page_hits)
    nb_pages = int(first.get("nbPages", 1) or 1)
    page = 1
    while page < nb_pages and page < MAX_PAGES:
        payload = fetcher(search_url(start, end, page=page, hits_per_page=hits_per_page))
        hits.extend(payload.get("hits", []) or [])
        page += 1
    return hits


def fetch_day_hits(target_date, fetcher=None, hits_per_page=DEFAULT_HITS_PER_PAGE) -> list:
    """Collect all Algolia hits created on ``target_date``.

    Splits the day into time windows as needed to defeat Algolia's per-query
    pagination cap, so the full day is captured. ``fetcher`` defaults to
    :func:`fetch_json` but is injectable for tests. The returned hits are the raw
    Algolia objects, untouched.
    """
    fetcher = fetch_json if fetcher is None else fetcher
    start, end = day_epoch_bounds(target_date)
    return _fetch_window(start, end, fetcher, hits_per_page)


def filter_hits_within_day(hits, start, end) -> list:
    """Keep only hits whose ``created_at_i`` falls in ``[start, end)``.

    A client-side guard against an API range filter behaving unexpectedly. Read
    only: it never mutates the hits it keeps.
    """
    kept = []
    for hit in hits:
        created = hit.get("created_at_i")
        if created is None:
            continue
        if start <= int(created) < end:
            kept.append(hit)
    return kept


def count_by_type(hits) -> dict:
    """Count hits per spec type using each hit's raw ``_tags``.

    ``ask`` is a subset of ``story`` (Ask HN posts carry both tags), so a single
    Ask HN post increments both ``story`` and ``ask`` — matching how the spec
    enumerates the two metrics. Read only: nothing is mutated.
    """
    counts = {item_type: 0 for item_type in ITEM_TYPES}
    for hit in hits:
        tags = hit.get("_tags") or []
        for item_type, tag in TYPE_TAGS.items():
            if tag in tags:
                counts[item_type] += 1
    return counts


def to_jsonl(hits) -> bytes:
    """Serialize hits as JSONL bytes: one raw object per line, in fetch order.

    The objects are written as-is (no field stripping or reordering beyond JSON
    key ordering for stable output).
    """
    lines = [json.dumps(hit, sort_keys=True, ensure_ascii=False) for hit in hits]
    text = "\n".join(lines)
    if text:
        text += "\n"
    return text.encode("utf-8")


def build_metadata(target_date, ingestion_date, record_count, counts_by_type, source_tags=QUERY_TAGS) -> dict:
    """Build the Hacker News ``metadata.json`` payload.

    Contains every field required by the plan/spec: target date, ingestion date,
    record count, and counts by type.
    """
    return {
        "source": SOURCE_NAME,
        "api": "algolia-search_by_date",
        "target_date": target_date,
        "ingestion_date": ingestion_date,
        "record_count": record_count,
        "counts_by_type": counts_by_type,
        "query_tags": list(source_tags),
        "format": "jsonl",
        "raw": True,
    }
