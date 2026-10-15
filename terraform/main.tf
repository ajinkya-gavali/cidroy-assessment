# main.tf
# Root module: wires together all sub-modules for the catalogue sync infrastructure.

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

module "s3" {
  source      = "./modules/s3"
  environment = var.environment
  project     = var.project
}

module "dynamodb" {
  source      = "./modules/dynamodb"
  environment = var.environment
  project     = var.project
}

module "secrets" {
  source                   = "./modules/secrets"
  environment              = var.environment
  project                  = var.project
  product_api_key_value    = var.product_api_key
  warehouse_api_key_value  = var.warehouse_api_key
}

module "iam" {
  source               = "./modules/iam"
  environment          = var.environment
  project              = var.project
  s3_bucket_arn        = module.s3.bucket_arn
  dynamodb_table_arns  = module.dynamodb.table_arns
  secret_arns          = module.secrets.secret_arns
}

module "ecs" {
  source                = "./modules/ecs"
  environment           = var.environment
  project               = var.project
  aws_region            = var.aws_region
  container_image       = var.container_image
  task_execution_role   = module.iam.task_execution_role_arn
  task_role             = module.iam.task_role_arn
  product_api_url       = var.product_api_url
  warehouse_api_url     = var.warehouse_api_url
  product_api_key_arn   = module.secrets.product_api_key_arn
  warehouse_api_key_arn = module.secrets.warehouse_api_key_arn
  s3_bucket_name        = module.s3.bucket_name
  runs_table_name       = module.dynamodb.runs_table_name
  batches_table_name    = module.dynamodb.batches_table_name
  dlq_table_name        = module.dynamodb.dlq_table_name
}

module "eventbridge" {
  source             = "./modules/eventbridge"
  environment        = var.environment
  project            = var.project
  schedule           = var.sync_schedule
  ecs_cluster_arn    = module.ecs.cluster_arn
  ecs_task_arn       = module.ecs.task_definition_arn
  task_role_arn      = module.iam.task_role_arn
  subnet_ids         = var.subnet_ids
  security_group_ids = var.security_group_ids
}

module "alarms" {
  source          = "./modules/alarms"
  environment     = var.environment
  project         = var.project
  log_group_name  = "/ecs/${var.project}-${var.environment}"
  alarm_email     = var.alarm_email
}
