data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "bronze_lambda" {
  name               = "${local.name_prefix}-bronze-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = local.common_tags
}

data "aws_iam_policy_document" "bronze_lambda_s3" {
  statement {
    sid = "WriteBronzeObjects"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:PutObject",
    ]
    resources = [
      "${aws_s3_bucket.data_lake.arn}/${var.bronze_prefix}/*",
    ]
  }
}

resource "aws_iam_policy" "bronze_lambda_s3" {
  name        = "${local.name_prefix}-bronze-lambda-s3"
  description = "Allows bronze ingestion Lambdas to write raw objects to the bronze prefix."
  policy      = data.aws_iam_policy_document.bronze_lambda_s3.json

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "bronze_lambda_s3" {
  role       = aws_iam_role.bronze_lambda.name
  policy_arn = aws_iam_policy.bronze_lambda_s3.arn
}

resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.bronze_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}
