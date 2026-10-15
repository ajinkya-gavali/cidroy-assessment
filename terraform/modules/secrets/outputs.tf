output "product_api_key_arn" {
  description = "ARN of the PIM API key secret"
  value       = aws_secretsmanager_secret.product_api_key.arn
}

output "warehouse_api_key_arn" {
  description = "ARN of the WMS API key secret"
  value       = aws_secretsmanager_secret.warehouse_api_key.arn
}

output "secret_arns" {
  description = "ARNs of all secrets"
  value = [
    aws_secretsmanager_secret.product_api_key.arn,
    aws_secretsmanager_secret.warehouse_api_key.arn,
  ]
}
