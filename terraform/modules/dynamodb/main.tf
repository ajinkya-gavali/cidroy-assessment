# modules/dynamodb/main.tf
# DynamoDB tables for run tracking, batch checkpointing, and dead-letter storage.

resource "aws_dynamodb_table" "sync_runs" {
  name         = "CatalogueSyncRuns-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "run_id"

  attribute {
    name = "run_id"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  tags = {
    Project     = var.project
    Environment = var.environment
  }
}

resource "aws_dynamodb_table" "sync_batches" {
  name         = "CatalogueSyncBatches-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "run_id"
  range_key    = "batch_id"

  attribute {
    name = "run_id"
    type = "S"
  }

  attribute {
    name = "batch_id"
    type = "S"
  }

  tags = {
    Project     = var.project
    Environment = var.environment
  }
}

resource "aws_dynamodb_table" "sync_dlq" {
  name         = "CatalogueSyncDLQ-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "run_id"
  range_key    = "sk"

  attribute {
    name = "run_id"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  tags = {
    Project     = var.project
    Environment = var.environment
  }
}
