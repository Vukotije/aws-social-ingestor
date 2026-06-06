data "archive_file" "gold_to_postgres_lambda" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/gold_to_postgres"
  output_path = "${path.module}/gold_to_postgres.zip"
}

resource "aws_iam_role" "gold_to_postgres_lambda" {
  name               = "${local.name_prefix}-gold-to-postgres-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = merge(local.common_tags, {
    Layer = "gold"
  })
}

data "aws_iam_policy_document" "gold_to_postgres_lambda" {
  statement {
    sid = "ListGoldPrefix"
    actions = [
      "s3:ListBucket",
    ]
    resources = [
      aws_s3_bucket.data_lake.arn,
    ]
  }

  statement {
    sid = "ReadGoldObjects"
    actions = [
      "s3:GetObject",
    ]
    resources = [
      "${aws_s3_bucket.data_lake.arn}/${var.gold_prefix}/*",
    ]
  }

  statement {
    sid = "ReadPostgresSecret"
    actions = [
      "secretsmanager:GetSecretValue",
    ]
    resources = [
      aws_secretsmanager_secret.postgres_password.arn,
    ]
  }
}

resource "aws_iam_policy" "gold_to_postgres_lambda" {
  name        = "${local.name_prefix}-gold-to-postgres-lambda"
  description = "Allows the gold-to-PostgreSQL loader to read gold outputs and database credentials."
  policy      = data.aws_iam_policy_document.gold_to_postgres_lambda.json

  tags = merge(local.common_tags, {
    Layer = "gold"
  })
}

resource "aws_iam_role_policy_attachment" "gold_to_postgres_lambda" {
  role       = aws_iam_role.gold_to_postgres_lambda.name
  policy_arn = aws_iam_policy.gold_to_postgres_lambda.arn
}

resource "aws_iam_role_policy_attachment" "gold_to_postgres_basic_execution" {
  role       = aws_iam_role.gold_to_postgres_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "gold_to_postgres" {
  function_name    = "${local.name_prefix}-gold-to-postgres"
  role             = aws_iam_role.gold_to_postgres_lambda.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  filename         = data.archive_file.gold_to_postgres_lambda.output_path
  source_code_hash = data.archive_file.gold_to_postgres_lambda.output_base64sha256
  timeout          = 120
  memory_size      = 256

  environment {
    variables = {
      DATA_LAKE_BUCKET                = aws_s3_bucket.data_lake.bucket
      GOLD_PREFIX                     = var.gold_prefix
      POSTGRES_DB                     = "social_metrics"
      POSTGRES_HOST                   = "pending-postgres-host"
      POSTGRES_PASSWORD_SECRET_ARN    = aws_secretsmanager_secret.postgres_password.arn
      POSTGRES_USER                   = "social_loader"
      NOTIFICATION_WEBHOOK_SECRET_ARN = aws_secretsmanager_secret.notification_webhook.arn
    }
  }

  tags = merge(local.common_tags, {
    Layer = "gold"
  })
}
