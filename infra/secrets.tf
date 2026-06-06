resource "aws_secretsmanager_secret" "postgres_password" {
  name        = "${local.name_prefix}/postgres/password"
  description = "Placeholder secret for the PostgreSQL password used by the gold loader."

  tags = merge(local.common_tags, {
    Layer = "gold"
  })
}

resource "aws_secretsmanager_secret" "notification_webhook" {
  name        = "${local.name_prefix}/notifications/webhook"
  description = "Placeholder secret for the failure notification webhook."

  tags = merge(local.common_tags, {
    Layer = "notifications"
  })
}
