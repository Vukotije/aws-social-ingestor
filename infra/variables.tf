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

variable "vpc_cidr" {
  description = "CIDR block for the project VPC."
  type        = string
  default     = "10.40.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets used by EC2-hosted services."
  type        = list(string)
  default     = ["10.40.1.0/24", "10.40.2.0/24"]
}

variable "admin_cidr_blocks" {
  description = "CIDR blocks allowed to reach Superset/SSH. Keep narrow for defense deployments."
  type        = list(string)
  default     = ["127.0.0.1/32"]
}

variable "silver_prefix" {
  description = "S3 prefix for silver-layer objects."
  type        = string
  default     = "silver"
}

variable "gold_prefix" {
  description = "S3 prefix for gold-layer objects."
  type        = string
  default     = "gold"
}
