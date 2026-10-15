variable "project" {
  description = "Project name"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "product_api_key_value" {
  description = "Value of PIM API key"
  type        = string
  sensitive   = true
}

variable "warehouse_api_key_value" {
  description = "Value of WMS API key"
  type        = string
  sensitive   = true
}
