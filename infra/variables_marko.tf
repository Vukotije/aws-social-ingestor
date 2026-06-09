# Variables for Marko's slice (gold metrics, Superset/PostgreSQL EC2, and
# failure notifications). Kept in a dedicated file so the shared variables.tf
# stays owned by the foundation slice.

variable "notification_platform" {
  description = "Chat platform for failure notifications. Only 'discord' is implemented; the payload is generic JSON that most webhook receivers accept."
  type        = string
  default     = "discord"
}

variable "awswrangler_layer_arn" {
  description = "ARN of an AWS SDK for pandas (awswrangler) Lambda layer for the gold Lambda's Parquet I/O. Leave empty to attach no layer (e.g. for terraform validate or when packaging deps another way)."
  type        = string
  default     = ""
}

variable "superset_instance_type" {
  description = "EC2 instance type for the combined PostgreSQL + Apache Superset host."
  type        = string
  default     = "t4g.medium"
}

variable "ec2_key_name" {
  description = "Optional EC2 key pair name for SSH access to the Superset/PostgreSQL host. Empty means no SSH key is attached."
  type        = string
  default     = ""
}

variable "postgres_db_name" {
  description = "PostgreSQL database that holds the gold metric tables Superset reads."
  type        = string
  default     = "social_metrics"
}

variable "postgres_app_user" {
  description = "PostgreSQL user that owns the gold metric tables."
  type        = string
  default     = "social_loader"
}

variable "superset_admin_user" {
  description = "Initial Apache Superset admin username."
  type        = string
  default     = "admin"
}
