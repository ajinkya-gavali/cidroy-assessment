# modules/eventbridge/outputs.tf
# Outputs from the EventBridge Scheduler module.

output "scheduler_arn" {
  description = "ARN of the EventBridge Scheduler schedule"
  value       = aws_scheduler_schedule.daily_sync.arn
}

output "scheduler_name" {
  description = "Name of the EventBridge Scheduler schedule"
  value       = aws_scheduler_schedule.daily_sync.name
}
