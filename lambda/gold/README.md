# Gold Metrics (Marko)

Computes every metric and KPI from `PROJECT_SPECIFICATION.md` section 3 from the
silver `users`/`posts` datasets and writes them as partitioned Parquet under the
gold prefix.

## Metrics produced

| Gold table | Requirement |
| --- | --- |
| `daily_hn_item_counts` | Daily counts of `story`/`ask`/`comment`/`job`/`poll` |
| `daily_users_metric` | Daily HN users and daily X users (new / total / active) |
| `top_x_users_by_followers` | Top 10 X users by followers |
| `top_hn_users_by_karma_high` | Top 10 HN users by highest karma |
| `top_hn_users_by_karma_low` | Top 10 HN users by lowest karma |
| `top_hn_jobs_by_score` | Top 10 HN jobs by score |
| `top_hn_stories_by_score` | Top 10 HN stories by score |
| `data_quality_score` | **KPI**: % of silver rows that are valid (non-null required fields) |

The compute logic in `metrics.py` is pure Python (lists of dicts in, rows out) —
no pandas/AWS — so every metric is unit tested in `tests/test_gold_metrics.py`.
`handler.py` does the Parquet/S3 I/O at the edges (awswrangler, imported lazily).

## Silver input contract

`silver_contract.py` documents the exact silver shape these metrics read. It is
**Vukan's** silver slice that produces it; freeze the columns together before
relying on gold output (Integration Milestone #1). If silver lands on different
names, update that one file.

## S3 layout

```text
s3://<DATA_LAKE_BUCKET>/gold/
└── <table>/
    └── metric_date=YYYY-MM-DD/            # daily_users_metric also partitions by platform=
        └── *.parquet
```

## Run locally

```bash
# Dry run on the bundled sample silver (no AWS, prints per-table row counts):
python lambda/gold/handler.py

# Offline end-to-end: read local silver JSONL, write gold as JSON files:
SILVER_LOCAL_DIR=lambda/gold/sample_silver \
  GOLD_LOCAL_OUTPUT_DIR=build/gold-out INGESTION_DATE=2026-01-16 \
  python lambda/gold/handler.py
find build/gold-out -type f

# Tests (with or without pytest):
python tests/test_gold_metrics.py
```

Real run: set `DATA_LAKE_BUCKET` (reads `silver/users|posts/` Parquet, writes
`gold/` Parquet). Needs the awswrangler layer (`var.awswrangler_layer_arn`).

## Integration handoffs

- **Step Functions**: `step_functions.tf` has a `GoldMetricsPlaceholder` Pass
  state — replace it with a Task invoking `aws_lambda_function.gold` (orchestration slice).
- **Loader / PostgreSQL**: the `daily_users_metric` and `data_quality_score`
  table shapes are shared with `db/gold_schema.sql`; reconcile `daily_users_metric`
  columns with Milos before the loader writes rows.
