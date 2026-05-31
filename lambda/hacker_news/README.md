# Hacker News Bronze Ingestion (Vukan)

This is Vukan's vertical slice of the bronze control point: collecting the
previous day's raw Hacker News items and landing them in S3 in raw form, with
metadata and mocked-API unit tests.

## Source / provenance

| Field | Value |
| --- | --- |
| Source | Hacker News |
| API | Hacker News Search API (Algolia), `search_by_date` endpoint |
| Endpoint | `https://hn.algolia.com/api/v1/search_by_date` |
| Query | One paginated request per day: `tags=(story,comment,poll,job)` + `numericFilters=created_at_i>=START,created_at_i<END` |
| Format | JSONL (one raw API hit per line) |

### Why the Search (Algolia) API instead of the official Firebase API

- The five required types (`story`, `ask`, `comment`, `job`, `poll`) map
  directly onto Algolia tags. `ask` is `ask_hn`, which the official Firebase
  `v0` API does not have at all (Ask HN posts are just stories there).
- "Items created the previous day" is a single date-range query, instead of
  walking tens of thousands of item ids from `maxitem` and fetching each one.
- Hits still carry the raw epoch `created_at_i`, so the later silver layer can
  still normalize timestamps to UTC.

`ask` is collected as a **subset of `story`** (an Ask HN post is tagged both
`story` and `ask_hn`). The daily query therefore uses only `story,comment,poll,job`
so each item is returned exactly once, and `metadata.json` derives the per-type
counts from each hit's raw `_tags`.

## Bronze rule (raw only)

Items are stored **exactly as the API returns them**, one JSON object per line.
The ingestion code does **not** clean HTML, normalize/convert timestamps,
flatten nested fields (e.g. `children`), map schemas, or deduplicate.
`count_by_type` only reads each hit's `_tags` to populate metadata.

## Exact S3 output path

Following the shared bronze layout:

```text
s3://<BRONZE_BUCKET>/<BRONZE_PREFIX>/hacker_news/ingestion_date=YYYY-MM-DD/
├── metadata.json
└── raw_items.jsonl
```

With defaults (`BRONZE_PREFIX=bronze`), e.g. for an ingestion on 2026-05-31
collecting the previous day:

```text
s3://<data-lake-bucket>/bronze/hacker_news/ingestion_date=2026-05-31/metadata.json
s3://<data-lake-bucket>/bronze/hacker_news/ingestion_date=2026-05-31/raw_items.jsonl
```

## `metadata.json` contents

Written next to the raw items; contains every plan/spec-required field:

```json
{
  "source": "hacker-news",
  "api": "algolia-search_by_date",
  "target_date": "2026-05-30",
  "ingestion_date": "2026-05-31",
  "record_count": 8421,
  "counts_by_type": {
    "story": 1200,
    "ask": 75,
    "comment": 7000,
    "job": 21,
    "poll": 1
  },
  "query_tags": ["story", "comment", "poll", "job"],
  "format": "jsonl",
  "raw": true
}
```

## Environment variables (shared contract)

| Name | Description |
| --- | --- |
| `BRONZE_BUCKET` | Target S3 bucket. When set, the handler fetches and uploads to S3. |
| `BRONZE_PREFIX` | Bronze prefix, defaults to `bronze`. |
| `INGESTION_DATE` | Optional override for the ingestion-date partition. |
| `TARGET_DATE` | Optional override for the source-data day; defaults to the day before the ingestion date. |
| `HN_LOCAL_OUTPUT_DIR` | Optional. When set (and `BRONZE_BUCKET` is unset), writes the exact bronze key layout to local disk instead of S3 — for offline sample runs / demos. |

Sink selection:

- `BRONZE_BUCKET` set -> fetch the day's items and upload to S3.
- `HN_LOCAL_OUTPUT_DIR` set -> fetch and write the same key layout to local disk.
- neither -> **dry run**: no network, no AWS; prints the keys/dates it would write.

## Run locally (repeatable script)

```bash
# Dry run — prints the keys + dates it would write, no network/AWS needed:
python3 lambda/hacker_news/handler.py

# Offline sample run — actually fetches the real previous day and writes the
# bronze layout to local disk (needs network, no AWS). build/ is gitignored:
HN_LOCAL_OUTPUT_DIR=build/sample-out INGESTION_DATE=2026-05-31 python3 lambda/hacker_news/handler.py
find build/sample-out -type f

# Real upload (needs network, AWS credentials, and a writable BRONZE_BUCKET):
BRONZE_BUCKET="$(cd infra && terraform output -raw data_lake_bucket)" \
  python3 lambda/hacker_news/handler.py
```

## Invoke and verify the deployed Lambda

```bash
cd infra

# Find the bucket and HN Lambda from Terraform outputs:
terraform output -raw data_lake_bucket
terraform output -raw hacker_news_lambda_name

# Manually invoke:
aws lambda invoke \
  --function-name "$(terraform output -raw hacker_news_lambda_name)" \
  --payload '{}' \
  hn-response.json
cat hn-response.json

# Confirm the raw items + metadata landed in S3:
aws s3 ls "s3://$(terraform output -raw data_lake_bucket)/$(terraform output -raw bronze_prefix)/hacker_news/" --recursive
```

## Tests

```bash
# Full unit suite (date filtering, item-type counting, pagination, key layout,
# metadata fields, raw preservation, dry-run + local-sink handler). The Algolia
# fetcher is injected, so no network or AWS is touched:
pytest tests/test_hacker_news_bronze.py
# or, without pytest:
python3 tests/test_hacker_news_bronze.py
```
