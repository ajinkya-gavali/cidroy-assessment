# outputs.tf

output "s3_bucket_name" {
  description = "S3 bucket name for catalogue exports"
  value       = module.s3.bucket_name
}

output "s3_bucket_arn" {
  description = "S3 bucket ARN"
  value       = module.s3.bucket_arn
}

output "ecs_cluster_arn" {
  description = "ECS Cluster ARN"
  value       = module.ecs.cluster_arn
}

output "task_definition_arn" {
  description = "ECS Task Definition ARN"
  value       = module.ecs.task_definition_arn
}

output "runs_table_name" {
  description = "DynamoDB table name for synchronization runs"
  value       = module.dynamodb.runs_table_name
}

output "batches_table_name" {
  description = "DynamoDB table name for batch records"
  value       = module.dynamodb.batches_table_name
}

output "alarms_sns_topic_arn" {
  description = "SNS topic ARN for CloudWatch alarm notifications"
  value       = module.alarms.sns_topic_arn
}

output "cloudwatch_dashboard_name" {
  description = "Name of the CloudWatch monitoring dashboard"
  value       = module.alarms.dashboard_name
}
