variable "project" {
  description = "Project name"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "s3_bucket_arn" {
  description = "ARN of the S3 bucket"
  type        = string
}

variable "dynamodb_table_arns" {
  description = "ARNs of DynamoDB tables"
  type        = list(string)
}

variable "secret_arns" {
  description = "ARNs of Secrets Manager secrets"
  type        = list(string)
}
