# modules/ecs/main.tf
# ECS Fargate cluster and task definition for the catalogue sync job.

resource "aws_ecs_cluster" "sync" {
  name = "${var.project}-${var.environment}"

  tags = {
    Project     = var.project
    Environment = var.environment
  }
}

resource "aws_cloudwatch_log_group" "sync" {
  name              = "/ecs/${var.project}-${var.environment}"
  retention_in_days = 30
}

resource "aws_ecs_task_definition" "sync" {
  family                   = "${var.project}-${var.environment}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "1024"   # 1 vCPU
  memory                   = "2048"   # 2 GB
  execution_role_arn       = var.task_execution_role
  task_role_arn            = var.task_role

  container_definitions = jsonencode([{
    name      = "catalogue-sync"
    image     = var.container_image
    essential = true

    command = ["python", "-m", "app.main"]

    environment = [
      { name = "APP_ENV",                value = "production" },
      { name = "AWS_REGION",             value = var.aws_region },
      { name = "PRODUCT_API_URL",        value = var.product_api_url },
      { name = "WAREHOUSE_API_URL",      value = var.warehouse_api_url },
      { name = "S3_BUCKET_NAME",         value = var.s3_bucket_name },
      { name = "DYNAMODB_RUNS_TABLE",    value = var.runs_table_name },
      { name = "DYNAMODB_BATCHES_TABLE", value = var.batches_table_name },
      { name = "DYNAMODB_DLQ_TABLE",     value = var.dlq_table_name },
    ]

    secrets = [
      { name = "PRODUCT_API_KEY",   valueFrom = var.product_api_key_arn },
      { name = "WAREHOUSE_API_KEY", valueFrom = var.warehouse_api_key_arn },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.sync.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "sync"
      }
    }
  }])
}
