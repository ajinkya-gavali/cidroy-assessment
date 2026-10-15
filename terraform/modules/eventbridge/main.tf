# modules/eventbridge/main.tf
# EventBridge scheduled rule to trigger the ECS Fargate sync task daily.

data "aws_iam_policy_document" "eventbridge_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "eventbridge" {
  name               = "${var.project}-${var.environment}-eventbridge-role"
  assume_role_policy = data.aws_iam_policy_document.eventbridge_assume.json
}

resource "aws_iam_role_policy" "eventbridge_ecs" {
  name = "allow-run-ecs-task"
  role = aws_iam_role.eventbridge.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ecs:RunTask"]
      Resource = var.ecs_task_arn
    }, {
      Effect   = "Allow"
      Action   = ["iam:PassRole"]
      Resource = [var.task_role_arn, "*"]
    }]
  })
}

resource "aws_scheduler_schedule" "daily_sync" {
  name                         = "${var.project}-${var.environment}-daily-sync"
  schedule_expression          = var.schedule
  schedule_expression_timezone = "UTC"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = var.ecs_cluster_arn
    role_arn = aws_iam_role.eventbridge.arn

    ecs_parameters {
      task_definition_arn = var.ecs_task_arn
      launch_type         = "FARGATE"

      network_configuration {
        assign_public_ip = false
        subnets          = var.subnet_ids
        security_groups  = var.security_group_ids
      }
    }
  }
}
