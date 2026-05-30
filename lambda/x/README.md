# X/Twitter Bronze Ingestion (Marko)

This is Marko's vertical slice of the bronze control point: the X/Twitter-style
dataset, the ingestion path that lands it in S3 in raw form, metadata, validation,
and the IAM/S3 review from the data-producer side.

## Dataset provenance

| Field | Value |
| --- | --- |
| Dataset name | `x-twitter-sample-2026` |
| File | [`dataset/x_sample_tweets.jsonl`](dataset/x_sample_tweets.jsonl) |
| Format | JSONL (one tweet object per line) |
| Source / provenance | **Synthetic, manually authored by the team** for the control point. Not collected from the live X/Twitter API. |
| Why synthetic | The free X API tier is too limited; the project spec explicitly allows using existing or generated datasets for the X source. |
| Shape | Mirrors the public X API v2 tweet object: nested `user` object (`username`, `verified`, `followers_count`, ...), `public_metrics`, ISO-8601 `created_at`, retweet markers. This gives the later silver layer realistic raw input to flatten/normalize. |
| Records | 25 tweets across 2026-01-14 → 2026-01-16, including 2 retweets and a mix of verified / non-verified users with a spread of follower counts. |

The format is JSONL (the shared contract allows `json`, `jsonl`, or `csv`).
JSONL was chosen because it keeps the raw nested API shape unambiguous and makes
row counting and format validation trivial.

## Bronze rule (raw only)

The dataset is uploaded **byte-for-byte** in its original form. The ingestion
code does **not** normalize, clean, deduplicate, convert timestamps, or write
Parquet. `count_records` only reads the bytes to report a row count for metadata;
the stored object is always the original file.

## Exact S3 output path

Following the shared bronze layout:

```text
s3://<BRONZE_BUCKET>/<BRONZE_PREFIX>/x/ingestion_date=YYYY-MM-DD/
├── metadata.json
└── raw_dataset.jsonl
```

With defaults (`BRONZE_PREFIX=bronze`), e.g. for an ingestion on 2026-05-31:

```text
s3://<data-lake-bucket>/bronze/x/ingestion_date=2026-05-31/metadata.json
s3://<data-lake-bucket>/bronze/x/ingestion_date=2026-05-31/raw_dataset.jsonl
```

## `metadata.json` contents

Written next to the raw dataset; contains every spec-required field:

```json
{
  "dataset_name": "x-twitter-sample-2026",
  "provenance": "Synthetic X/Twitter-style sample, manually authored ...",
  "format": "jsonl",
  "ingestion_date": "2026-05-31",
  "row_count": 25,
  "file_count": 1,
  "byte_count": 12345,
  "object_key": "bronze/x/ingestion_date=2026-05-31/raw_dataset.jsonl",
  "raw": true
}
```

## Environment variables (shared contract)

| Name | Description |
| --- | --- |
| `BRONZE_BUCKET` | Target S3 bucket. If unset, the script runs a local **dry run** (no upload). |
| `BRONZE_PREFIX` | Bronze prefix, defaults to `bronze`. |
| `INGESTION_DATE` | Optional override for the ingestion date partition. |
| `TARGET_DATE` | Optional source-data date; recorded in metadata when set. |
| `X_DATASET_PATH` | Optional path to a different dataset file (defaults to the bundled one). |
| `X_LOCAL_OUTPUT_DIR` | Optional. When set (and `BRONZE_BUCKET` is unset), writes the exact bronze key layout to local disk instead of S3 — for offline sample runs / demos. |

## Run locally (repeatable script)

```bash
# Dry run — prints the keys + metadata it would write, no AWS needed:
python lambda/x/handler.py

# Offline sample run — actually writes the bronze layout to local disk (no AWS).
# build/ is gitignored, so the demo output won't be committed:
X_LOCAL_OUTPUT_DIR=build/sample-out INGESTION_DATE=2026-05-31 python lambda/x/handler.py
find build/sample-out -type f

# Real upload (needs AWS credentials and a writable BRONZE_BUCKET):
BRONZE_BUCKET="$(cd infra && terraform output -raw data_lake_bucket)" \
  python lambda/x/handler.py
```

## Invoke and verify the deployed Lambda

```bash
cd infra

# Find the bucket and X Lambda from Terraform outputs:
terraform output -raw data_lake_bucket
terraform output -raw x_lambda_name
terraform output -raw x_bronze_prefix

# Manually invoke:
aws lambda invoke \
  --function-name "$(terraform output -raw x_lambda_name)" \
  --payload '{}' \
  x-response.json
cat x-response.json

# Confirm the raw dataset + metadata landed in S3:
aws s3 ls "s3://$(terraform output -raw data_lake_bucket)/$(terraform output -raw x_bronze_prefix)/" --recursive
```

## Validation

```bash
# Lightweight checks: file exists, valid JSONL, non-empty row count.
python lambda/x/validate.py

# Full unit suite (key layout, metadata fields, raw preservation, dry-run handler):
pytest tests/test_x_bronze.py
# or, without pytest:
python tests/test_x_bronze.py
```

The validation deliberately checks the **local** dataset bytes (the source of
truth for the upload). It does not read back from S3 — see the IAM note below.

## IAM / S3 review (data-producer side)

Reviewed `infra/iam.tf` to confirm the X ingestion path can only write to the
bronze prefix:

- The X Lambda reuses the shared `aws_iam_role.bronze_lambda` role.
- That role's only S3 grant is `aws_iam_policy.bronze_lambda_s3`, which allows
  **only** `s3:PutObject` and `s3:AbortMultipartUpload`, scoped to
  `"${aws_s3_bucket.data_lake.arn}/${var.bronze_prefix}/*"`.
- Result: the X Lambda can write under `bronze/` (including `bronze/x/...`) and
  **cannot** read objects, delete objects, or write outside the bronze prefix.
  Least privilege holds for the producer path.
- Consequence: because the role has no `s3:GetObject`, the Lambda cannot verify
  its own upload by reading it back. S3-side verification is therefore done
  out-of-band with operator credentials (the `aws s3 ls` / `aws lambda invoke`
  steps above), which is intentional.
