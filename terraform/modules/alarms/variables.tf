# modules/alarms/variables.tf
# Input variables for the CloudWatch Alarms & Dashboard module.

variable "project" {
  description = "Project name used for resource naming and tagging"
  type        = string
}

variable "environment" {
  description = "Deployment environment (e.g. prod, staging)"
  type        = string
}

variable "log_group_name" {
  description = "CloudWatch Logs group name emitted by the ECS task (e.g. /ecs/catalogue-sync-prod)"
  type        = string
}

variable "metric_namespace" {
  description = "CloudWatch custom metric namespace (must match app/core/metrics.py NAMESPACE)"
  type        = string
  default     = "CatalogueSync"
}

variable "alarm_email" {
  description = "Email address to receive SNS alarm notifications"
  type        = string
}

variable "rejected_products_threshold" {
  description = "Number of rejected products above which the DLQ alarm triggers"
  type        = number
  default     = 500
}

variable "ambiguous_timeout_threshold" {
  description = "Number of ambiguous timeouts above which the alarm triggers (default: any > 0)"
  type        = number
  default     = 0
}

variable "run_duration_threshold_seconds" {
  description = "ECS task duration in seconds above which the SLA-breach alarm triggers (default: 1500 = 25 min)"
  type        = number
  default     = 1500
}
