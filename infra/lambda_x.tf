# X/Twitter dataset bronze ingestion Lambda.
#
# NOTE (team coordination): per the KT plan the X Lambda *resource* is nominally
# Vukan's wiring task, while Marko owns the ingestion logic plus the variables/
# outputs needed to invoke and verify it. Vukan's resource was not yet present in
# the repo, so this minimal resource is included here to make Marko's invoke/
# verify outputs real and keep `terraform validate` green. It reuses Milos's
# shared bucket, shared bronze IAM role, and the shared environment contract.
# Reconcile with Vukan's version at integration time (keep one definition).
#
# Unlike Hacker News, the X dataset is a one-off/manual upload, so there is no
# EventBridge schedule here. It is invoked manually (see outputs + README).

data "archive_file" "x_lambda" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/x"
  output_path = "${path.module}/x.zip"
}

resource "aws_lambda_function" "x_ingest" {
  function_name    = "${local.name_prefix}-x-bronze"
  role             = aws_iam_role.bronze_lambda.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  filename         = data.archive_file.x_lambda.output_path
  source_code_hash = data.archive_file.x_lambda.output_base64sha256
  timeout          = 120
  memory_size      = 256

  environment {
    variables = {
      BRONZE_BUCKET = aws_s3_bucket.data_lake.bucket
      BRONZE_PREFIX = var.bronze_prefix
    }
  }

  tags = local.common_tags
}
