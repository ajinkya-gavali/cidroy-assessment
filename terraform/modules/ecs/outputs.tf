output "cluster_arn" {
  description = "ARN of the ECS Cluster"
  value       = aws_ecs_cluster.sync.arn
}

output "task_definition_arn" {
  description = "ARN of the ECS Task Definition"
  value       = aws_ecs_task_definition.sync.arn
}
