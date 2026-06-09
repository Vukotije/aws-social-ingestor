# Failure notifications (Marko's slice).
#
# An EventBridge rule watches the pipeline state machine (orchestration.tf /
# step_functions.tf) for terminal failures and invokes this Lambda, which posts
# a message to the Discord webhook stored in Secrets Manager (secrets.tf). The
# state machine's PipelineFailed state therefore surfaces in chat automatically,
# with no edits to the state machine definition itself.

data "archive_file" "notifications_lambda" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/notifications"
  output_path = "${path.module}/notifications.zip"
}

resource "aws_iam_role" "notifications_lambda" {
  name               = "${local.name_prefix}-notifications-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = merge(local.common_tags, {
    Layer = "notifications"
  })
}

data "aws_iam_policy_document" "notifications_lambda" {
  statement {
    sid       = "ReadNotificationWebhookSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.notification_webhook.arn]
  }
}

resource "aws_iam_policy" "notifications_lambda" {
  name        = "${local.name_prefix}-notifications-lambda"
  description = "Allows the notifications Lambda to read the webhook secret."
  policy      = data.aws_iam_policy_document.notifications_lambda.json

  tags = merge(local.common_tags, {
    Layer = "notifications"
  })
}

resource "aws_iam_role_policy_attachment" "notifications_lambda" {
  role       = aws_iam_role.notifications_lambda.name
  policy_arn = aws_iam_policy.notifications_lambda.arn
}

resource "aws_iam_role_policy_attachment" "notifications_basic_execution" {
  role       = aws_iam_role.notifications_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "notifications" {
  function_name    = "${local.name_prefix}-notifications"
  role             = aws_iam_role.notifications_lambda.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  filename         = data.archive_file.notifications_lambda.output_path
  source_code_hash = data.archive_file.notifications_lambda.output_base64sha256
  timeout          = 30
  memory_size      = 128

  environment {
    variables = {
      NOTIFICATION_PLATFORM           = var.notification_platform
      NOTIFICATION_WEBHOOK_SECRET_ARN = aws_secretsmanager_secret.notification_webhook.arn
    }
  }

  tags = merge(local.common_tags, {
    Layer = "notifications"
  })
}

# Fire only on terminal failure statuses of the medallion pipeline execution.
resource "aws_cloudwatch_event_rule" "pipeline_failed" {
  name        = "${local.name_prefix}-pipeline-failed"
  description = "Fires when the medallion pipeline state machine ends in a failed state."

  event_pattern = jsonencode({
    "source"      = ["aws.states"]
    "detail-type" = ["Step Functions Execution Status Change"]
    "detail" = {
      "stateMachineArn" = [aws_sfn_state_machine.pipeline.arn]
      "status"          = ["FAILED", "TIMED_OUT", "ABORTED"]
    }
  })

  tags = merge(local.common_tags, {
    Layer = "notifications"
  })
}

resource "aws_cloudwatch_event_target" "pipeline_failed_to_lambda" {
  rule      = aws_cloudwatch_event_rule.pipeline_failed.name
  target_id = "notifications-lambda"
  arn       = aws_lambda_function.notifications.arn
}

resource "aws_lambda_permission" "allow_eventbridge_notifications" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.notifications.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.pipeline_failed.arn
}

output "notifications_lambda_name" {
  description = "Failure-notification Lambda name."
  value       = aws_lambda_function.notifications.function_name
}

output "pipeline_failed_rule_name" {
  description = "EventBridge rule that triggers a notification on pipeline failure."
  value       = aws_cloudwatch_event_rule.pipeline_failed.name
}
