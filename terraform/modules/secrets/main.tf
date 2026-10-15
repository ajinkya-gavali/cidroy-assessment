# modules/secrets/main.tf
# AWS Secrets Manager secrets for PIM and WMS API keys.

resource "aws_secretsmanager_secret" "product_api_key" {
  name        = "${var.project}/${var.environment}/product_api_key"
  description = "PIM API authentication key for catalogue synchronization"

  tags = {
    Project     = var.project
    Environment = var.environment
  }
}

resource "aws_secretsmanager_secret_version" "product_api_key" {
  secret_id     = aws_secretsmanager_secret.product_api_key.id
  secret_string = jsonencode({ value = var.product_api_key_value })
}

resource "aws_secretsmanager_secret" "warehouse_api_key" {
  name        = "${var.project}/${var.environment}/warehouse_api_key"
  description = "WMS API authentication key for catalogue synchronization"

  tags = {
    Project     = var.project
    Environment = var.environment
  }
}

resource "aws_secretsmanager_secret_version" "warehouse_api_key" {
  secret_id     = aws_secretsmanager_secret.warehouse_api_key.id
  secret_string = jsonencode({ value = var.warehouse_api_key_value })
}
