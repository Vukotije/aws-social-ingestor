# Gold metric transformation Lambda (Marko's slice).
#
# Reads the silver `users`/`posts` Parquet datasets and writes the gold metric
# tables (lambda/gold/metrics.py) as partitioned Parquet under the gold prefix.
# Step Functions (step_functions.tf) has a GoldMetricsPlaceholder Pass state;
# wiring this function in there is an integration step owned with the
# orchestration slice.
#
# Parquet I/O needs the AWS SDK for pandas (awswrangler). Attach it via
# var.awswrangler_layer_arn (the AWS-managed layer ARN for the region). Left
# empty by default so `terraform validate`/`plan` work without picking a region
# ARN; set it before `apply`.

data "archive_file" "gold_lambda" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/gold"
  output_path = "${path.module}/gold.zip"
}

resource "aws_iam_role" "gold_lambda" {
  name               = "${local.name_prefix}-gold-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = merge(local.common_tags, {
    Layer = "gold"
  })
}

data "aws_iam_policy_document" "gold_lambda" {
  statement {
    sid       = "ListDataLake"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.data_lake.arn]
  }

  statement {
    sid       = "ReadSilverObjects"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/${var.silver_prefix}/*"]
  }

  statement {
    sid = "WriteGoldObjects"
    actions = [
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
    ]
    resources = ["${aws_s3_bucket.data_lake.arn}/${var.gold_prefix}/*"]
  }
}

resource "aws_iam_policy" "gold_lambda" {
  name        = "${local.name_prefix}-gold-lambda"
  description = "Allows the gold Lambda to read silver and write gold objects."
  policy      = data.aws_iam_policy_document.gold_lambda.json

  tags = merge(local.common_tags, {
    Layer = "gold"
  })
}

resource "aws_iam_role_policy_attachment" "gold_lambda" {
  role       = aws_iam_role.gold_lambda.name
  policy_arn = aws_iam_policy.gold_lambda.arn
}

resource "aws_iam_role_policy_attachment" "gold_lambda_basic_execution" {
  role       = aws_iam_role.gold_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "gold" {
  function_name    = "${local.name_prefix}-gold"
  role             = aws_iam_role.gold_lambda.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  filename         = data.archive_file.gold_lambda.output_path
  source_code_hash = data.archive_file.gold_lambda.output_base64sha256
  timeout          = 300
  memory_size      = 512
  layers           = var.awswrangler_layer_arn == "" ? [] : [var.awswrangler_layer_arn]

  environment {
    variables = {
      DATA_LAKE_BUCKET = aws_s3_bucket.data_lake.bucket
      SILVER_PREFIX    = var.silver_prefix
      GOLD_PREFIX      = var.gold_prefix
    }
  }

  tags = merge(local.common_tags, {
    Layer = "gold"
  })
}

output "gold_lambda_name" {
  description = "Gold metric transformation Lambda name."
  value       = aws_lambda_function.gold.function_name
}

output "gold_prefix_full" {
  description = "S3 prefix where gold metric Parquet datasets are written."
  value       = var.gold_prefix
}
