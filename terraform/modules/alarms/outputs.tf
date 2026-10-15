# modules/alarms/outputs.tf
# Outputs from the CloudWatch Alarms & Dashboard module.

output "sns_topic_arn" {
  description = "ARN of the SNS topic that receives alarm notifications"
  value       = aws_sns_topic.alarms.arn
}

output "alarm_high_dlq_arn" {
  description = "ARN of the high dead-letter / rejected products alarm"
  value       = aws_cloudwatch_metric_alarm.high_dlq_count.arn
}

output "alarm_ambiguous_timeout_arn" {
  description = "ARN of the ambiguous-timeout alarm"
  value       = aws_cloudwatch_metric_alarm.ambiguous_timeout_alert.arn
}

output "alarm_sla_breach_arn" {
  description = "ARN of the SLA-breach (task duration) alarm"
  value       = aws_cloudwatch_metric_alarm.sla_breach.arn
}

output "dashboard_name" {
  description = "Name of the CloudWatch Dashboard"
  value       = aws_cloudwatch_dashboard.sync_overview.dashboard_name
}

output "dashboard_arn" {
  description = "ARN of the CloudWatch Dashboard"
  value       = aws_cloudwatch_dashboard.sync_overview.dashboard_arn
}
