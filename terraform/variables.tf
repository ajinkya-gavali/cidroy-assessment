# variables.tf

variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "ap-south-1"
}

variable "environment" {
  description = "Deployment environment (e.g. prod, staging)"
  type        = string
  default     = "prod"
}

variable "project" {
  description = "Project name used for resource naming and tagging"
  type        = string
  default     = "catalogue-sync"
}

variable "container_image" {
  description = "Docker image URI for the sync application (ECR or DockerHub)"
  type        = string
}

variable "product_api_url" {
  description = "PIM API base URL"
  type        = string
}

variable "warehouse_api_url" {
  description = "WMS API base URL"
  type        = string
}

variable "product_api_key" {
  description = "API key for the PIM service (stored in Secrets Manager)"
  type        = string
  sensitive   = true
}

variable "warehouse_api_key" {
  description = "API key for the WMS service (stored in Secrets Manager)"
  type        = string
  sensitive   = true
}

variable "sync_schedule" {
  description = "EventBridge cron expression for daily sync (UTC)"
  type        = string
  default     = "cron(0 6 * * ? *)"
}

variable "subnet_ids" {
  description = "VPC subnet IDs for ECS Fargate tasks"
  type        = list(string)
  default     = []
}

variable "security_group_ids" {
  description = "Security group IDs for ECS Fargate tasks"
  type        = list(string)
  default     = []
}

variable "alarm_email" {
  description = "Email address to receive CloudWatch alarm notifications via SNS"
  type        = string
  default     = ""
}
