# Marko's slice: Gold metrics + Superset/PostgreSQL + Notifications

Implements the three areas assigned to Marko in `FULL_IMPLEMENTATION_PLAN.md`,
built on top of Milos's cloud foundation (VPC, Step Functions, Secrets,
gold->PostgreSQL loader).

## What's here

| Area | Code / IaC | Status |
| --- | --- | --- |
| Gold metric Lambdas | `lambda/gold/`, `infra/lambda_gold.tf`, `db/gold_metrics.sql` | ✅ logic + tests + IaC; needs real silver |
| Notifications | `lambda/notifications/`, `infra/notifications.tf` | ✅ logic + tests + IaC |
| Superset + PostgreSQL on EC2 | `infra/viz_ec2.tf`, `infra/templates/…`, `infra/SUPERSET.md` | ✅ IaC; user-data verify-on-deploy |

## Verify locally

Stdlib only — unit + e2e + the real-HTTP notification path (no AWS, no deps):

```bash
python tests/test_gold_metrics.py                    # 11 metric/KPI unit tests
python tests/test_notifications.py                   # 10 notification unit tests
python tests/test_e2e_gold_pipeline.py               # 3 e2e: silver files -> gold files
python tests/test_integration_notifications_http.py  # 2 integration: real HTTP POST to a local server
python lambda/gold/handler.py                        # dry-run: 8 gold tables from sample silver
python lambda/notifications/handler.py               # dry-run: Discord payload for a sample failure
cd infra && terraform fmt -check && terraform validate
```

Real Parquet/S3 path (needs the Lambda data deps):

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python tests/test_integration_gold_s3_parquet.py   # silver Parquet -> handler -> gold Parquet (moto S3)
```

62 tests total: all green with the deps; 61 green + 1 skipped on the stdlib alone.

## Integration handoffs (cross-team touchpoints)

These deliberately stay out of teammates' files; they are the points to reconcile
at integration:

1. **Silver contract (with Vukan)** — gold reads the schema in
   `lambda/gold/silver_contract.py`. Freeze `users`/`posts` columns together
   before gold runs on real data (Integration Milestone #1).
2. **Step Functions (with Milos)** — replace the `GoldMetricsPlaceholder` Pass
   state with a Task invoking `aws_lambda_function.gold`, and expand the
   `LoadGoldToPostgres` `metric_tables` list to all gold tables.
3. **gold->PostgreSQL loader (with Milos)** — set its `POSTGRES_HOST` to
   `terraform output -raw viz_private_dns`, run it inside the VPC with the
   `lambda` security group (to reach 5432), and reconcile the `daily_users_metric`
   columns between `db/gold_schema.sql` and `db/gold_metrics.sql`.
4. **Secrets before deploy** — put a real PostgreSQL password and Discord webhook
   into the Secrets Manager placeholders (`secrets.tf`). See `infra/SUPERSET.md`
   and `lambda/notifications/README.md`.
5. **awswrangler layer before apply** — set `var.awswrangler_layer_arn` to the
   AWS SDK for pandas layer ARN for the region so the gold Lambda can write Parquet.

## Branch note

This work is based on `feat/cloud-foundation` (Milos's foundation), because the
notifications and Superset pieces reference his Step Functions, VPC, and secrets.
Rebase / merge onto `main` once that foundation lands on `main`.
