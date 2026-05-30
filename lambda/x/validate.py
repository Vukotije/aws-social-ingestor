"""Lightweight validation for the X bronze upload shape.

Checks Marko's deliverable requires:
  * file existence
  * readable format (valid JSONL)
  * row count (non-empty, and optionally matches a metadata count)

This validates the *local* dataset bytes (the source of truth for what gets
uploaded). It deliberately does not read back from S3: the shared bronze IAM
policy grants the ingestion role ``s3:PutObject`` only (write-only to the bronze
prefix), so the Lambda itself cannot GET objects. S3-side verification is done
out-of-band with operator credentials (see lambda/x/README.md).

Runnable as a script:

    python lambda/x/validate.py                 # validates the bundled dataset
    python lambda/x/validate.py path/to/file    # validates an arbitrary file
"""

from __future__ import annotations

import json
import os

import x_ingest


class ValidationError(Exception):
    """Raised when the dataset fails a validation check."""


def validate_file_exists(path):
    if not os.path.isfile(path):
        raise ValidationError("dataset file not found: {0}".format(path))


def validate_jsonl_readable(raw_bytes):
    """Parse JSONL and return the list of records, or raise ValidationError."""
    records = []
    for line_no, line in enumerate(raw_bytes.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            records.append(json.loads(stripped))
        except json.JSONDecodeError as exc:
            raise ValidationError(
                "line {0} is not valid JSON: {1}".format(line_no, exc)
            ) from exc
    if not records:
        raise ValidationError("dataset is empty: no JSON records found")
    return records


def validate_row_count(records, expected):
    if len(records) != expected:
        raise ValidationError(
            "row count mismatch: file has {0}, metadata says {1}".format(
                len(records), expected
            )
        )


def validate_dataset(path=None, expected_row_count=None):
    """Run all checks against a dataset file. Returns a summary dict on success."""
    path = path or x_ingest.default_dataset_path()
    validate_file_exists(path)
    with open(path, "rb") as handle:
        raw = handle.read()
    records = validate_jsonl_readable(raw)
    if expected_row_count is not None:
        validate_row_count(records, expected_row_count)
    return {
        "path": path,
        "format": x_ingest.DATASET_FORMAT,
        "row_count": len(records),
        "byte_count": len(raw),
    }


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else None
    summary = validate_dataset(target)
    print("OK: {0}".format(json.dumps(summary)))
