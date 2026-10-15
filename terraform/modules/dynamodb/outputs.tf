output "runs_table_name" {
  description = "Name of the DynamoDB runs table"
  value       = aws_dynamodb_table.sync_runs.name
}

output "batches_table_name" {
  description = "Name of the DynamoDB batches table"
  value       = aws_dynamodb_table.sync_batches.name
}

output "dlq_table_name" {
  description = "Name of the DynamoDB DLQ table"
  value       = aws_dynamodb_table.sync_dlq.name
}

output "table_arns" {
  description = "ARNs of all DynamoDB tables"
  value = [
    aws_dynamodb_table.sync_runs.arn,
    aws_dynamodb_table.sync_batches.arn,
    aws_dynamodb_table.sync_dlq.arn,
  ]
}
