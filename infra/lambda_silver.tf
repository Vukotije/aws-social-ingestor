# Silver normalization Lambda (Vukan's slice).
#
# Reads a day's raw bronze JSONL for both sources and writes the normalized
# silver `users`/`posts` Parquet datasets (lambda/silver/normalize.py) under the
# silver prefix, where the gold metric Lambda reads them back.
#
# NOTE: this Lambda enriches Hacker News users with their karma from the public
# Algolia users endpoint, so it needs outbound internet access. It is deployed as
# a default (non-VPC) Lambda, which has internet egress out of the box; if it is
# ever moved into a VPC it will need a NAT gateway (or the enrichment disabled
# via HN_ENRICH_USERS=0).
#
# Parquet I/O needs the AWS SDK for pandas (awswrangler). Attach it via
# var.awswrangler_layer_arn (the AWS-managed layer ARN for the region). Left
# empty by default so `terraform validate`/`plan` work without picking a region
# ARN; set it before `apply`.

data "archive_file" "silver_lambda" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/silver"
  output_path = "${path.module}/silver.zip"
}

resource "aws_iam_role" "silver_lambda" {
  name               = "${local.name_prefix}-silver-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = merge(local.common_tags, {
    Layer = "silver"
  })
}

data "aws_iam_policy_document" "silver_lambda" {
  statement {
    sid       = "ListDataLake"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.data_lake.arn]
  }

  statement {
    sid       = "ReadBronzeObjects"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/${var.bronze_prefix}/*"]
  }

  statement {
    sid = "WriteSilverObjects"
    actions = [
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
    ]
    resources = ["${aws_s3_bucket.data_lake.arn}/${var.silver_prefix}/*"]
  }
}

resource "aws_iam_policy" "silver_lambda" {
  name        = "${local.name_prefix}-silver-lambda"
  description = "Allows the silver Lambda to read bronze and write silver objects."
  policy      = data.aws_iam_policy_document.silver_lambda.json

  tags = merge(local.common_tags, {
    Layer = "silver"
  })
}

resource "aws_iam_role_policy_attachment" "silver_lambda" {
  role       = aws_iam_role.silver_lambda.name
  policy_arn = aws_iam_policy.silver_lambda.arn
}

resource "aws_iam_role_policy_attachment" "silver_lambda_basic_execution" {
  role       = aws_iam_role.silver_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "silver" {
  function_name    = "${local.name_prefix}-silver"
  role             = aws_iam_role.silver_lambda.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  filename         = data.archive_file.silver_lambda.output_path
  source_code_hash = data.archive_file.silver_lambda.output_base64sha256
  timeout          = 300
  memory_size      = 512
  layers           = var.awswrangler_layer_arn == "" ? [] : [var.awswrangler_layer_arn]

  environment {
    variables = {
      DATA_LAKE_BUCKET = aws_s3_bucket.data_lake.bucket
      BRONZE_PREFIX    = var.bronze_prefix
      SILVER_PREFIX    = var.silver_prefix
    }
  }

  tags = merge(local.common_tags, {
    Layer = "silver"
  })
}

output "silver_lambda_name" {
  description = "Silver normalization Lambda name."
  value       = aws_lambda_function.silver.function_name
}
