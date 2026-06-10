data "aws_iam_policy_document" "step_functions_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "pipeline_state_machine" {
  name               = "${local.name_prefix}-pipeline-state-machine"
  assume_role_policy = data.aws_iam_policy_document.step_functions_assume_role.json

  tags = merge(local.common_tags, {
    Layer = "orchestration"
  })
}

data "aws_iam_policy_document" "pipeline_state_machine" {
  statement {
    sid = "InvokePipelineLambdas"
    actions = [
      "lambda:InvokeFunction",
    ]
    resources = [
      aws_lambda_function.hacker_news_ingest.arn,
      aws_lambda_function.x_ingest.arn,
      aws_lambda_function.silver.arn,
      aws_lambda_function.gold.arn,
      aws_lambda_function.gold_to_postgres.arn,
    ]
  }
}

resource "aws_iam_policy" "pipeline_state_machine" {
  name        = "${local.name_prefix}-pipeline-state-machine"
  description = "Allows the pipeline state machine to invoke project Lambdas."
  policy      = data.aws_iam_policy_document.pipeline_state_machine.json

  tags = merge(local.common_tags, {
    Layer = "orchestration"
  })
}

resource "aws_iam_role_policy_attachment" "pipeline_state_machine" {
  role       = aws_iam_role.pipeline_state_machine.name
  policy_arn = aws_iam_policy.pipeline_state_machine.arn
}

resource "aws_sfn_state_machine" "pipeline" {
  name     = "${local.name_prefix}-medallion-pipeline"
  role_arn = aws_iam_role.pipeline_state_machine.arn

  definition = jsonencode({
    Comment = "Medallion pipeline orchestration: bronze ingestion -> silver normalization -> gold metrics -> PostgreSQL load."
    StartAt = "IngestHackerNews"
    States = {
      IngestHackerNews = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.hacker_news_ingest.arn
          Payload      = {}
        }
        ResultPath = "$.hacker_news"
        Catch = [{
          ErrorEquals = ["States.ALL"]
          ResultPath  = "$.error"
          Next        = "PipelineFailed"
        }]
        Next = "IngestXDataset"
      }
      IngestXDataset = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.x_ingest.arn
          Payload      = {}
        }
        ResultPath = "$.x"
        Catch = [{
          ErrorEquals = ["States.ALL"]
          ResultPath  = "$.error"
          Next        = "PipelineFailed"
        }]
        Next = "SilverNormalization"
      }
      SilverNormalization = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.silver.arn
          Payload      = {}
        }
        ResultPath = "$.silver"
        Catch = [{
          ErrorEquals = ["States.ALL"]
          ResultPath  = "$.error"
          Next        = "PipelineFailed"
        }]
        Next = "GoldMetrics"
      }
      GoldMetrics = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.gold.arn
          Payload      = {}
        }
        ResultPath = "$.gold"
        Catch = [{
          ErrorEquals = ["States.ALL"]
          ResultPath  = "$.error"
          Next        = "PipelineFailed"
        }]
        Next = "LoadGoldToPostgres"
      }
      LoadGoldToPostgres = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.gold_to_postgres.arn
          Payload = {
            metric_tables = [
              "daily_hn_item_counts",
              "daily_users_metric",
              "top_x_users_by_followers",
              "top_hn_users_by_karma_high",
              "top_hn_users_by_karma_low",
              "top_hn_jobs_by_score",
              "top_hn_stories_by_score",
              "data_quality_score",
            ]
          }
        }
        ResultPath = "$.postgres"
        Catch = [{
          ErrorEquals = ["States.ALL"]
          ResultPath  = "$.error"
          Next        = "PipelineFailed"
        }]
        Next = "PipelineSucceeded"
      }
      PipelineSucceeded = {
        Type = "Succeed"
      }
      PipelineFailed = {
        Type  = "Fail"
        Error = "PipelineFailed"
        Cause = "A pipeline task failed. Notification wiring is owned by the notifications slice."
      }
    }
  })

  tags = merge(local.common_tags, {
    Layer = "orchestration"
  })
}
