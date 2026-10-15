# modules/s3/main.tf
# S3 bucket for catalogue exports with 90-day lifecycle expiration.

resource "aws_s3_bucket" "catalogue_exports" {
  bucket = "${var.project}-exports-${var.environment}"

  tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_s3_bucket_versioning" "catalogue_exports" {
  bucket = aws_s3_bucket.catalogue_exports.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "catalogue_exports" {
  bucket = aws_s3_bucket.catalogue_exports.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "catalogue_exports" {
  bucket                  = aws_s3_bucket.catalogue_exports.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "export_retention" {
  bucket = aws_s3_bucket.catalogue_exports.id

  rule {
    id     = "expire-exports-after-90-days"
    status = "Enabled"

    expiration {
      days = 90
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

resource "aws_s3_bucket_policy" "enforce_tls" {
  bucket = aws_s3_bucket.catalogue_exports.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "EnforceTLS"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [
        aws_s3_bucket.catalogue_exports.arn,
        "${aws_s3_bucket.catalogue_exports.arn}/*",
      ]
      Condition = {
        Bool = { "aws:SecureTransport" = "false" }
      }
    }]
  })
}
