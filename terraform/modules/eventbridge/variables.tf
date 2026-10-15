variable "project" { type = string }
variable "environment" { type = string }
variable "schedule" { type = string }
variable "ecs_cluster_arn" { type = string }
variable "ecs_task_arn" { type = string }
variable "task_role_arn" { type = string }
variable "subnet_ids" { type = list(string) }
variable "security_group_ids" { type = list(string) }
