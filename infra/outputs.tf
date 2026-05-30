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
