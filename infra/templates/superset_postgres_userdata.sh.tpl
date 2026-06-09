#!/bin/bash
# Marko's slice: provision PostgreSQL + Apache Superset on this EC2 host via
# Docker Compose. Terraform injects: aws_region, db_name, db_user,
# password_secret_arn, superset_admin_user, and the gold metric DDL.
# Bash/compose variables are written escaped so templatefile leaves them for the
# shell; Terraform-injected values use single-dollar interpolation.
set -euxo pipefail

dnf update -y
dnf install -y docker awscli openssl
systemctl enable --now docker

# Docker Compose v2 as a CLI plugin (arm64 host).
mkdir -p /usr/local/lib/docker/cli-plugins
curl -sSL "https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-aarch64" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

APP_DIR=/opt/viz
mkdir -p "$${APP_DIR}/initdb"

# Gold metric schema, applied by PostgreSQL on first initialization.
cat > "$${APP_DIR}/initdb/gold_metrics.sql" <<'SQL'
${gold_metrics_sql}
SQL

# Resolve the PostgreSQL password from Secrets Manager (the team sets this secret
# before deploy). Fall back to a clearly-flagged placeholder if it is empty.
PG_PASSWORD="$(aws secretsmanager get-secret-value --region ${aws_region} \
  --secret-id ${password_secret_arn} --query SecretString --output text 2>/dev/null || true)"
if [ -z "$${PG_PASSWORD}" ] || [ "$${PG_PASSWORD}" = "None" ]; then
  PG_PASSWORD="changeme-set-postgres-password-secret"
  echo "WARNING: postgres password secret is empty; using placeholder password" >&2
fi

SUPERSET_SECRET_KEY="$(openssl rand -base64 42)"

cat > "$${APP_DIR}/docker-compose.yml" <<COMPOSE
services:
  postgres:
    image: postgres:16
    restart: always
    environment:
      POSTGRES_DB: ${db_name}
      POSTGRES_USER: ${db_user}
      POSTGRES_PASSWORD: "$${PG_PASSWORD}"
    volumes:
      - pgdata:/var/lib/postgresql/data
      - $${APP_DIR}/initdb:/docker-entrypoint-initdb.d:ro
    ports:
      - "5432:5432"
  superset:
    image: apache/superset:3.1.1
    restart: always
    depends_on:
      - postgres
    environment:
      SUPERSET_SECRET_KEY: "$${SUPERSET_SECRET_KEY}"
      TALISMAN_ENABLED: "False"
    ports:
      - "8088:8088"
volumes:
  pgdata:
COMPOSE

cd "$${APP_DIR}"
docker compose up -d

# Bootstrap Superset. Give PostgreSQL/Superset a moment to come up first; if any
# step fails the instance can be re-bootstrapped by re-running these commands.
sleep 45
docker compose exec -T superset superset db upgrade
docker compose exec -T superset superset fab create-admin \
  --username ${superset_admin_user} --firstname Admin --lastname User \
  --email admin@example.com --password "$${PG_PASSWORD}" || true
docker compose exec -T superset superset init
