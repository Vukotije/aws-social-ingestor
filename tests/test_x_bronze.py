"""Unit tests for Marko's X/Twitter bronze ingestion path.

Covers the upload shape (S3 keys), metadata fields, row counting, raw
preservation, and the validation helpers. No AWS / boto3 required: the handler
runs in dry-run mode when ``BRONZE_BUCKET`` is unset.

Runnable two ways:
    pytest tests/test_x_bronze.py
    python tests/test_x_bronze.py
"""

from __future__ import annotations

import contextlib
import json
import os
import sys

# The Lambda source dir is added to sys.path so the package modules import as
# top-level names (``lambda`` is a Python keyword, so it cannot be imported as a
# package). This mirrors how the Lambda runtime resolves ``handler.lambda_handler``.
HERE = os.path.dirname(os.path.abspath(__file__))
X_SRC = os.path.join(HERE, "..", "lambda", "x")
sys.path.insert(0, X_SRC)

import x_ingest  # noqa: E402
import validate  # noqa: E402
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


def _dataset_bytes():
    with open(x_ingest.default_dataset_path(), "rb") as handle:
        return handle.read()


# --- S3 key / contract layout -------------------------------------------------

def test_object_keys_match_shared_contract():
    keys = x_ingest.build_object_keys("2026-05-30", "bronze")
    assert keys["raw_key"] == "bronze/x/ingestion_date=2026-05-30/raw_dataset.jsonl"
    assert keys["metadata_key"] == "bronze/x/ingestion_date=2026-05-30/metadata.json"


def test_object_keys_respect_custom_prefix():
    keys = x_ingest.build_object_keys("2026-05-30", "/custom/")
    assert keys["raw_key"].startswith("custom/x/ingestion_date=2026-05-30/")


# --- ingestion date resolution -----------------------------------------------

def test_ingestion_date_env_override_wins():
    assert x_ingest.resolve_ingestion_date({"INGESTION_DATE": "2020-01-02"}) == "2020-01-02"


def test_ingestion_date_uses_injected_today_when_no_override():
    import datetime

    assert x_ingest.resolve_ingestion_date({}, today=datetime.date(2026, 5, 30)) == "2026-05-30"


# --- row counting -------------------------------------------------------------

def test_count_records_ignores_blank_lines():
    raw = b'{"a":1}\n\n{"b":2}\n   \n{"c":3}\n'
    assert x_ingest.count_records(raw) == 3


def test_count_records_matches_validation_parse_on_real_dataset():
    raw = _dataset_bytes()
    parsed = validate.validate_jsonl_readable(raw)
    assert x_ingest.count_records(raw) == len(parsed) > 0


# --- metadata -----------------------------------------------------------------

def test_metadata_contains_all_required_fields():
    meta = x_ingest.build_metadata(
        ingestion_date="2026-05-30",
        row_count=25,
        byte_count=12345,
        raw_key="bronze/x/ingestion_date=2026-05-30/raw_dataset.jsonl",
    )
    # Spec: dataset name, provenance, format, ingestion date, and row/file count.
    for field in ("dataset_name", "provenance", "format", "ingestion_date", "row_count", "file_count"):
        assert field in meta, "missing required metadata field: {0}".format(field)
    assert meta["file_count"] == 1
    assert meta["row_count"] == 25
    assert meta["format"] == "jsonl"
    assert meta["raw"] is True
    assert meta["provenance"]  # non-empty provenance string


def test_metadata_includes_target_date_only_when_provided():
    without = x_ingest.build_metadata(
        ingestion_date="2026-05-30", row_count=1, byte_count=1, raw_key="k"
    )
    assert "target_date" not in without
    with_target = x_ingest.build_metadata(
        ingestion_date="2026-05-30", row_count=1, byte_count=1, raw_key="k", target_date="2026-01-15"
    )
    assert with_target["target_date"] == "2026-01-15"


# --- handler dry run (no AWS) -------------------------------------------------

def test_handler_dry_run_matches_dataset():
    with env(BRONZE_BUCKET=None, X_LOCAL_OUTPUT_DIR=None, BRONZE_PREFIX="bronze", INGESTION_DATE="2026-05-30", TARGET_DATE=None):
        result = handler.lambda_handler({}, None)

    body = result["body"]
    assert result["statusCode"] == 200
    assert body["dry_run"] is True
    assert body["keys"]["raw_key"] == "bronze/x/ingestion_date=2026-05-30/raw_dataset.jsonl"

    expected_rows = x_ingest.count_records(_dataset_bytes())
    assert body["row_count"] == expected_rows
    assert body["metadata"]["row_count"] == expected_rows
    assert body["metadata"]["object_key"] == body["keys"]["raw_key"]


def test_handler_dry_run_passes_through_target_date():
    with env(BRONZE_BUCKET=None, X_LOCAL_OUTPUT_DIR=None, INGESTION_DATE="2026-05-30", TARGET_DATE="2026-01-15"):
        body = handler.lambda_handler({}, None)["body"]
    assert body["metadata"]["target_date"] == "2026-01-15"


def test_handler_local_sink_writes_both_files_in_bronze_layout(tmp_path=None):
    import tempfile

    out = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp()
    with env(BRONZE_BUCKET=None, X_LOCAL_OUTPUT_DIR=out, BRONZE_PREFIX="bronze", INGESTION_DATE="2026-05-30", TARGET_DATE=None):
        body = handler.lambda_handler({}, None)["body"]

    assert body["sink"] == "local"
    base = os.path.join(out, "bronze", "x", "ingestion_date=2026-05-30")
    raw_path = os.path.join(base, "raw_dataset.jsonl")
    meta_path = os.path.join(base, "metadata.json")
    assert os.path.isfile(raw_path)
    assert os.path.isfile(meta_path)

    # Raw object is byte-for-byte identical to the source dataset (no transformation).
    with open(raw_path, "rb") as handle:
        assert handle.read() == _dataset_bytes()

    with open(meta_path) as handle:
        meta = json.load(handle)
    assert meta["row_count"] == x_ingest.count_records(_dataset_bytes())
    assert meta["file_count"] == 1
    assert meta["provenance"]


# --- raw preservation ---------------------------------------------------------

def test_dataset_is_valid_raw_jsonl_with_nested_shape():
    """Every line parses and keeps the raw nested X API shape (no flattening)."""
    records = validate.validate_jsonl_readable(_dataset_bytes())
    assert len(records) > 0
    for rec in records:
        # Raw structure preserved: nested user object + public_metrics + epoch-free ISO time.
        assert isinstance(rec.get("user"), dict)
        assert "username" in rec["user"]
        assert isinstance(rec.get("public_metrics"), dict)
        assert rec["created_at"].endswith("Z")  # ISO-8601, left un-normalized on purpose


# --- validation helpers -------------------------------------------------------

def test_validate_dataset_ok_on_bundled_file():
    summary = validate.validate_dataset()
    assert summary["row_count"] > 0
    assert summary["format"] == "jsonl"


def test_validate_dataset_row_count_match():
    expected = x_ingest.count_records(_dataset_bytes())
    summary = validate.validate_dataset(expected_row_count=expected)
    assert summary["row_count"] == expected


def test_validate_rejects_row_count_mismatch():
    try:
        validate.validate_dataset(expected_row_count=999999)
    except validate.ValidationError:
        pass
    else:
        raise AssertionError("expected ValidationError for row count mismatch")


def test_validate_rejects_missing_file(tmp_path=None):
    missing = os.path.join(X_SRC, "dataset", "does_not_exist.jsonl")
    try:
        validate.validate_dataset(missing)
    except validate.ValidationError:
        pass
    else:
        raise AssertionError("expected ValidationError for missing file")


def test_validate_rejects_malformed_jsonl():
    try:
        validate.validate_jsonl_readable(b'{"ok":1}\n{not valid json}\n')
    except validate.ValidationError:
        pass
    else:
        raise AssertionError("expected ValidationError for malformed JSONL")


def test_validate_rejects_empty():
    try:
        validate.validate_jsonl_readable(b"\n   \n")
    except validate.ValidationError:
        pass
    else:
        raise AssertionError("expected ValidationError for empty dataset")


def _run_all():
    """Minimal runner so the file works without pytest (python tests/test_x_bronze.py)."""
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for func in funcs:
        func()
        passed += 1
        print("ok  - {0}".format(func.__name__))
    print("\n{0} passed".format(passed))


if __name__ == "__main__":
    _run_all()
