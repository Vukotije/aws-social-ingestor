"""Unit tests for Vukan's Hacker News bronze ingestion path.

Covers date/epoch bounds, date filtering, item-type counting from raw ``_tags``,
pagination via a fake fetcher, the upload shape (S3 keys), metadata fields, raw
byte preservation, and the dry-run / local-sink handler. No network or AWS: the
Algolia fetcher is injected, and the handler runs in dry-run mode when neither
``BRONZE_BUCKET`` nor ``HN_LOCAL_OUTPUT_DIR`` is set.

Runnable two ways:
    pytest tests/test_hacker_news_bronze.py
    python tests/test_hacker_news_bronze.py
"""

from __future__ import annotations

import contextlib
import datetime
import json
import os
import sys
from urllib.parse import parse_qs, urlparse

# The Lambda source dir is added to sys.path so the package modules import as
# top-level names (``lambda`` is a Python keyword, so it cannot be imported as a
# package). This mirrors how the Lambda runtime resolves ``handler.lambda_handler``.
HERE = os.path.dirname(os.path.abspath(__file__))
HN_SRC = os.path.join(HERE, "..", "lambda", "hacker_news")
sys.path.insert(0, HN_SRC)

import hn_ingest  # noqa: E402
import handler  # noqa: E402


@contextlib.contextmanager
def env(**overrides):
    """Temporarily set/clear env vars, restoring the original environment after."""
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


def _epoch(date_str, hour=12):
    """Epoch seconds for a given UTC date at ``hour`` (default noon)."""
    day = datetime.datetime.strptime(date_str, "%Y-%m-%d").replace(
        hour=hour, tzinfo=datetime.timezone.utc
    )
    return int(day.timestamp())


def _hit(object_id, tags, created_at_i, **extra):
    hit = {"objectID": str(object_id), "_tags": list(tags), "created_at_i": created_at_i}
    hit.update(extra)
    return hit


class PagedFetcher:
    """Fake Algolia fetcher returning canned pages keyed by the URL ``page`` param."""

    def __init__(self, pages):
        self.pages = pages  # list of lists of hits
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        page = int(parse_qs(urlparse(url).query).get("page", ["0"])[0])
        hits = self.pages[page] if page < len(self.pages) else []
        return {"hits": hits, "nbPages": len(self.pages), "page": page}


# --- S3 key / contract layout -------------------------------------------------

def test_object_keys_match_shared_contract():
    keys = hn_ingest.build_object_keys("2026-05-31", "bronze")
    assert keys["raw_key"] == "bronze/hacker_news/ingestion_date=2026-05-31/raw_items.jsonl"
    assert keys["metadata_key"] == "bronze/hacker_news/ingestion_date=2026-05-31/metadata.json"


def test_object_keys_respect_custom_prefix():
    keys = hn_ingest.build_object_keys("2026-05-31", "/custom/")
    assert keys["raw_key"].startswith("custom/hacker_news/ingestion_date=2026-05-31/")


# --- ingestion / target date resolution --------------------------------------

def test_ingestion_date_env_override_wins():
    assert hn_ingest.resolve_ingestion_date({"INGESTION_DATE": "2020-01-02"}) == "2020-01-02"


def test_ingestion_date_uses_injected_today_when_no_override():
    assert hn_ingest.resolve_ingestion_date({}, today=datetime.date(2026, 5, 31)) == "2026-05-31"


def test_target_date_defaults_to_previous_day():
    assert hn_ingest.resolve_target_date({}, ingestion_date="2026-05-31") == "2026-05-30"
    # Month boundary.
    assert hn_ingest.resolve_target_date({}, ingestion_date="2026-06-01") == "2026-05-31"


def test_target_date_env_override_wins():
    assert hn_ingest.resolve_target_date({"TARGET_DATE": "2026-01-15"}, ingestion_date="2026-05-31") == "2026-01-15"


# --- epoch day bounds ---------------------------------------------------------

def test_day_epoch_bounds_are_utc_midnight_to_next_midnight():
    start, end = hn_ingest.day_epoch_bounds("2026-05-30")
    assert start == int(datetime.datetime(2026, 5, 30, tzinfo=datetime.timezone.utc).timestamp())
    assert end == int(datetime.datetime(2026, 5, 31, tzinfo=datetime.timezone.utc).timestamp())
    assert end - start == 24 * 60 * 60


# --- search URL ---------------------------------------------------------------

def test_search_url_contains_range_and_tags():
    start, end = hn_ingest.day_epoch_bounds("2026-05-30")
    url = hn_ingest.search_url(start, end, page=2, hits_per_page=500)
    qs = parse_qs(urlparse(url).query)
    assert qs["page"] == ["2"]
    assert qs["hitsPerPage"] == ["500"]
    assert qs["numericFilters"] == ["created_at_i>={0},created_at_i<{1}".format(start, end)]
    # Query tags exclude ask_hn (collected via the story tag) so items aren't duplicated.
    assert qs["tags"] == ["(story,comment,poll,job)"]


# --- date filtering -----------------------------------------------------------

def test_filter_hits_within_day_excludes_out_of_range():
    start, end = hn_ingest.day_epoch_bounds("2026-05-30")
    hits = [
        _hit("in", ["story"], _epoch("2026-05-30", hour=0)),       # inclusive lower bound
        _hit("mid", ["story"], _epoch("2026-05-30", hour=23)),     # in range
        _hit("next", ["story"], _epoch("2026-05-31", hour=0)),     # exclusive upper bound -> out
        _hit("prev", ["story"], _epoch("2026-05-29", hour=23)),    # before -> out
        _hit("none", ["story"], None),                              # missing time -> out
    ]
    kept = hn_ingest.filter_hits_within_day(hits, start, end)
    kept_ids = {h["objectID"] for h in kept}
    assert kept_ids == {"in", "mid"}


# --- item type counting -------------------------------------------------------

def test_count_by_type_from_tags_treats_ask_as_story_subset():
    hits = [
        _hit(1, ["story"], 1),
        _hit(2, ["story", "ask_hn"], 1),   # Ask HN: counts as both story and ask
        _hit(3, ["comment"], 1),
        _hit(4, ["comment"], 1),
        _hit(5, ["job"], 1),
        _hit(6, ["poll"], 1),
        _hit(7, ["story", "show_hn"], 1),  # Show HN: a story, not ask
    ]
    counts = hn_ingest.count_by_type(hits)
    assert counts == {"story": 3, "ask": 1, "comment": 2, "job": 1, "poll": 1}


# --- raw JSONL serialization --------------------------------------------------

def test_to_jsonl_one_raw_object_per_line_preserves_data():
    hits = [_hit(1, ["story"], 100, title="Hello <p>world</p>"), _hit(2, ["comment"], 200)]
    raw = hn_ingest.to_jsonl(hits)
    lines = raw.decode("utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    # Raw preservation: HTML left untouched, nested fields intact, nothing stripped.
    assert first["title"] == "Hello <p>world</p>"
    assert first["objectID"] == "1"
    assert json.loads(lines[1])["objectID"] == "2"
    # Trailing newline so the file is well-formed JSONL.
    assert raw.endswith(b"\n")


def test_to_jsonl_empty_is_empty_bytes():
    assert hn_ingest.to_jsonl([]) == b""


# --- pagination ---------------------------------------------------------------

def test_fetch_day_hits_paginates_until_last_page():
    pages = [
        [_hit(1, ["story"], 10), _hit(2, ["comment"], 11)],
        [_hit(3, ["job"], 12)],
    ]
    fetcher = PagedFetcher(pages)
    hits = hn_ingest.fetch_day_hits("2026-05-30", fetcher=fetcher)
    assert [h["objectID"] for h in hits] == ["1", "2", "3"]
    assert len(fetcher.calls) == 2  # stopped after nbPages reached


def test_fetch_day_hits_splits_window_when_over_pagination_cap():
    """A day reporting more than the reachable cap is split by time, losslessly."""
    start, end = hn_ingest.day_epoch_bounds("2026-05-30")
    mid = start + (end - start) // 2

    def fetcher(url):
        qs = parse_qs(urlparse(url).query)
        nf = qs["numericFilters"][0]
        w_start = int(nf.split("created_at_i>=")[1].split(",")[0])
        w_end = int(nf.split("created_at_i<")[1])
        if (w_start, w_end) == (start, end):
            # Whole-day window is over the cap -> must be split, hits unreachable here.
            return {"hits": [], "nbHits": hn_ingest.PAGINATION_LIMIT + 500, "nbPages": 1}
        if (w_start, w_end) == (start, mid):
            return {"hits": [_hit(1, ["story"], w_start)], "nbHits": 1, "nbPages": 1}
        if (w_start, w_end) == (mid, end):
            return {"hits": [_hit(2, ["comment"], w_start)], "nbHits": 1, "nbPages": 1}
        raise AssertionError("unexpected window {0}".format((w_start, w_end)))

    hits = hn_ingest.fetch_day_hits("2026-05-30", fetcher=fetcher)
    assert {h["objectID"] for h in hits} == {"1", "2"}  # both halves captured, no loss


# --- metadata -----------------------------------------------------------------

def test_metadata_contains_all_required_fields():
    counts = {"story": 3, "ask": 1, "comment": 2, "job": 1, "poll": 1}
    meta = hn_ingest.build_metadata(
        target_date="2026-05-30",
        ingestion_date="2026-05-31",
        record_count=7,
        counts_by_type=counts,
    )
    for field in ("target_date", "ingestion_date", "record_count", "counts_by_type"):
        assert field in meta, "missing required metadata field: {0}".format(field)
    assert meta["target_date"] == "2026-05-30"
    assert meta["ingestion_date"] == "2026-05-31"
    assert meta["record_count"] == 7
    assert meta["counts_by_type"] == counts
    assert meta["raw"] is True


# --- handler dry run (no network, no AWS) -------------------------------------

def test_handler_dry_run_does_not_fetch():
    def explode(_url):  # must never be called in dry run
        raise AssertionError("dry run must not hit the network")

    with env(BRONZE_BUCKET=None, HN_LOCAL_OUTPUT_DIR=None, BRONZE_PREFIX="bronze", INGESTION_DATE="2026-05-31", TARGET_DATE=None):
        result = handler.lambda_handler({}, None, fetcher=explode)

    body = result["body"]
    assert result["statusCode"] == 200
    assert body["dry_run"] is True
    assert body["target_date"] == "2026-05-30"
    assert body["keys"]["raw_key"] == "bronze/hacker_news/ingestion_date=2026-05-31/raw_items.jsonl"


# --- handler local sink (mocked fetcher) --------------------------------------

def test_handler_local_sink_writes_both_files_in_bronze_layout():
    import tempfile

    pages = [[
        _hit(1, ["story"], _epoch("2026-05-30", hour=8), title="A <i>story</i>"),
        _hit(2, ["story", "ask_hn"], _epoch("2026-05-30", hour=9)),
        _hit(3, ["comment"], _epoch("2026-05-30", hour=10)),
        _hit(99, ["story"], _epoch("2026-05-31", hour=1)),  # next day -> filtered out
    ]]
    fetcher = PagedFetcher(pages)

    out = tempfile.mkdtemp()
    with env(BRONZE_BUCKET=None, HN_LOCAL_OUTPUT_DIR=out, BRONZE_PREFIX="bronze", INGESTION_DATE="2026-05-31", TARGET_DATE=None):
        body = handler.lambda_handler({}, None, fetcher=fetcher)["body"]

    assert body["sink"] == "local"
    assert body["record_count"] == 3  # out-of-range hit filtered
    assert body["counts_by_type"] == {"story": 2, "ask": 1, "comment": 1, "job": 0, "poll": 0}

    base = os.path.join(out, "bronze", "hacker_news", "ingestion_date=2026-05-31")
    raw_path = os.path.join(base, "raw_items.jsonl")
    meta_path = os.path.join(base, "metadata.json")
    assert os.path.isfile(raw_path)
    assert os.path.isfile(meta_path)

    # Raw preservation: 3 kept lines, HTML untouched.
    with open(raw_path, "rb") as fh:
        lines = fh.read().decode("utf-8").splitlines()
    assert len(lines) == 3
    assert json.loads(lines[0])["title"] == "A <i>story</i>"

    with open(meta_path) as fh:
        meta = json.load(fh)
    assert meta["record_count"] == 3
    assert meta["target_date"] == "2026-05-30"
    assert meta["counts_by_type"]["ask"] == 1


def _run_all():
    """Minimal runner so the file works without pytest (python tests/test_hacker_news_bronze.py)."""
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for func in funcs:
        func()
        passed += 1
        print("ok  - {0}".format(func.__name__))
    print("\n{0} passed".format(passed))


if __name__ == "__main__":
    _run_all()
