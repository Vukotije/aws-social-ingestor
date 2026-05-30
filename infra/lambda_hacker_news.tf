data "archive_file" "hacker_news_lambda" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/hacker_news"
  output_path = "${path.module}/hacker_news.zip"
}

resource "aws_lambda_function" "hacker_news_ingest" {
  function_name    = "${local.name_prefix}-hacker-news-bronze"
  role             = aws_iam_role.bronze_lambda.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  filename         = data.archive_file.hacker_news_lambda.output_path
  source_code_hash = data.archive_file.hacker_news_lambda.output_base64sha256
  timeout          = 900
  memory_size      = 512

  environment {
    variables = {
      BRONZE_BUCKET = aws_s3_bucket.data_lake.bucket
      BRONZE_PREFIX = var.bronze_prefix
    }
  }

  tags = local.common_tags
}

resource "aws_cloudwatch_event_rule" "daily_hacker_news_ingest" {
  name                = "${local.name_prefix}-daily-hacker-news-ingest"
  description         = "Runs Hacker News bronze ingestion once per day."
  schedule_expression = var.hacker_news_schedule_expression

  tags = local.common_tags
}

resource "aws_cloudwatch_event_target" "daily_hacker_news_ingest" {
  rule      = aws_cloudwatch_event_rule.daily_hacker_news_ingest.name
  target_id = "hacker-news-bronze"
  arn       = aws_lambda_function.hacker_news_ingest.arn
}

resource "aws_lambda_permission" "allow_eventbridge_hacker_news" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.hacker_news_ingest.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily_hacker_news_ingest.arn
}
