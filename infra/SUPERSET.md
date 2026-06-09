# Visualization: Apache Superset + PostgreSQL on EC2 (Marko's slice)

One EC2 instance (`aws_instance.viz`, `viz_ec2.tf`) hosts PostgreSQL and Apache
Superset via Docker Compose, inside Milos's VPC and using his `superset` /
`postgres` security groups. The gold metric tables (`db/gold_metrics.sql`) are
created on first boot.

## Deploy

```bash
cd infra
# 1. Put a real PostgreSQL password into the secret the host reads on boot:
aws secretsmanager put-secret-value \
  --secret-id "$(terraform output -raw postgres_password_secret_arn)" \
  --secret-string 'CHANGE-ME-strong-password'

# 2. Restrict who can reach Superset/SSH (defaults to 127.0.0.1/32):
terraform apply -var='admin_cidr_blocks=["<your.ip>/32"]'

# 3. Get the URL (Superset listens on :8088):
terraform output -raw superset_url
```

First boot takes a few minutes (Docker pulls postgres + superset images and
bootstraps the Superset metadata DB). Admin login: `superset_admin_user`
(default `admin`); the initial admin password is set to the PostgreSQL password
from the secret — change it in the UI after first login.

## Connect Superset to the metrics database

In Superset: **Settings -> Database Connections -> + Database -> PostgreSQL**

```text
HOST:     localhost      (PostgreSQL runs on the same EC2 host)
PORT:     5432
DATABASE: social_metrics
USER:     social_loader
PASSWORD: <the secret value from above>
```

SQLAlchemy URI: `postgresql://social_loader:<password>@localhost:5432/social_metrics`

## Datasets and charts (one per required metric/KPI)

Add each gold table as a dataset, then a chart:

| Gold table | Suggested chart |
| --- | --- |
| `daily_hn_item_counts` | Stacked bar / time-series, X=`metric_date`, series=`post_type`, Y=`item_count` |
| `daily_users_metric` | Time-series line, X=`metric_date`, series=`platform`, Y=`new_users` and `total_users` |
| `top_x_users_by_followers` | Bar (sorted), `username` vs `followers_count` |
| `top_hn_users_by_karma_high` | Bar, `username` vs `karma_score` |
| `top_hn_users_by_karma_low` | Bar, `username` vs `karma_score` (ascending) |
| `top_hn_jobs_by_score` | Table, `rank`/`score`/`content_text` |
| `top_hn_stories_by_score` | Table, `rank`/`score`/`content_text` |
| `data_quality_score` | Big Number with `quality_score`, one per `source` |

Assemble the charts into one **"Social Media Metrics"** dashboard, add a
`metric_date` filter, and capture screenshots for the defense.

## Getting data into PostgreSQL

The gold Lambda writes Parquet to `s3://<bucket>/gold/<table>/...`. The
gold->PostgreSQL loader (Milos's `lambda/gold_to_postgres`) is the production
path; it must:

- set `POSTGRES_HOST` to this host (`terraform output -raw viz_private_dns`),
- run inside the VPC with the `lambda` security group to reach port 5432,
- agree on the `daily_users_metric` columns (see the note in `db/gold_metrics.sql`).

For a quick dashboard demo before the loader is finished, you can load a single
day directly. Produce local JSON with the gold handler and `\copy` it, or insert
a few representative rows by hand — the table shapes match `db/gold_metrics.sql`.

## Notes / verification

- This user-data is best-effort and should be verified on a real deploy: confirm
  `docker compose ps` shows both services healthy and Superset answers on :8088.
- Re-bootstrap if needed: SSH in, `cd /opt/viz`, re-run the `docker compose exec
  -T superset ...` commands from the user-data script.
- Least privilege: the host's instance profile can read only the PostgreSQL
  password secret; the `superset` SG exposes only 8088/22 to `admin_cidr_blocks`;
  `postgres` SG allows 5432 only from the `lambda` and `superset` SGs.
