variable "aws_region" {
  description = "AWS region used for the control-point deployment."
  type        = string
  default     = "eu-central-1"
}

variable "project_name" {
  description = "Project name used in AWS resource names and tags."
  type        = string
  default     = "aws-social-ingestor"
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
  default     = "dev"
}

variable "bronze_prefix" {
  description = "S3 prefix for bronze-layer objects."
  type        = string
  default     = "bronze"
}

variable "hacker_news_schedule_expression" {
  description = "EventBridge schedule expression for daily Hacker News ingestion."
  type        = string
  default     = "cron(0 2 * * ? *)"
}
