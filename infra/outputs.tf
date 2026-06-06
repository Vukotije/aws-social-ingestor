output "data_lake_bucket" {
  description = "S3 bucket for bronze-layer data."
  value       = aws_s3_bucket.data_lake.bucket
}

output "bronze_prefix" {
  description = "S3 prefix for bronze-layer objects."
  value       = var.bronze_prefix
}

output "bronze_lambda_role_arn" {
  description = "Shared IAM role ARN for bronze ingestion Lambdas."
  value       = aws_iam_role.bronze_lambda.arn
}

output "hacker_news_lambda_name" {
  description = "Hacker News bronze ingestion Lambda name."
  value       = aws_lambda_function.hacker_news_ingest.function_name
}

output "hacker_news_schedule_name" {
  description = "EventBridge schedule rule for Hacker News ingestion."
  value       = aws_cloudwatch_event_rule.daily_hacker_news_ingest.name
}

# X/Twitter bronze ingestion outputs (Marko) — sufficient to find the bucket and
# X Lambda for a manual invoke and to locate the raw output in S3.
output "x_lambda_name" {
  description = "X/Twitter bronze ingestion Lambda name."
  value       = aws_lambda_function.x_ingest.function_name
}

output "x_lambda_arn" {
  description = "X/Twitter bronze ingestion Lambda ARN."
  value       = aws_lambda_function.x_ingest.arn
}

output "x_bronze_prefix" {
  description = "S3 key prefix where the X/Twitter raw dataset and metadata are written."
  value       = "${var.bronze_prefix}/x"
}

output "vpc_id" {
  description = "Project VPC ID."
  value       = aws_vpc.main.id
}

output "public_subnet_ids" {
  description = "Public subnet IDs for EC2-hosted PostgreSQL/Superset services."
  value       = aws_subnet.public[*].id
}

output "lambda_security_group_id" {
  description = "Security group ID for project Lambdas that later need VPC access."
  value       = aws_security_group.lambda.id
}

output "postgres_security_group_id" {
  description = "Security group ID for PostgreSQL."
  value       = aws_security_group.postgres.id
}

output "superset_security_group_id" {
  description = "Security group ID for Superset."
  value       = aws_security_group.superset.id
}

output "pipeline_state_machine_arn" {
  description = "Step Functions state machine ARN for the full medallion pipeline."
  value       = aws_sfn_state_machine.pipeline.arn
}

output "gold_to_postgres_lambda_name" {
  description = "Gold-to-PostgreSQL loader Lambda name."
  value       = aws_lambda_function.gold_to_postgres.function_name
}

output "postgres_password_secret_arn" {
  description = "Secrets Manager ARN for the PostgreSQL password placeholder."
  value       = aws_secretsmanager_secret.postgres_password.arn
}

output "notification_webhook_secret_arn" {
  description = "Secrets Manager ARN for the notification webhook placeholder."
  value       = aws_secretsmanager_secret.notification_webhook.arn
}
