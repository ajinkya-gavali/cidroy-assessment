# modules/alarms/main.tf
# CloudWatch Alarms, SNS notification topic, and pre-built monitoring Dashboard
# for the catalogue synchronisation ECS job.
#
# Application emits custom metrics under the "CatalogueSync" namespace (see
# app/core/metrics.py):
#   - WmsProductsAccepted   (Count)
#   - WmsProductsRejected   (Count)
#   - WmsAmbiguousTimeouts  (Count)
#
# Container logs flow to the log group created by modules/ecs/ under
#   /ecs/<project>-<environment>

locals {
  name_prefix = "${var.project}-${var.environment}"
}

# ---------------------------------------------------------------------------
# SNS Topic — receives alarm state-change notifications
# ---------------------------------------------------------------------------

resource "aws_sns_topic" "alarms" {
  name = "${local.name_prefix}-alarms"

  tags = {
    Project     = var.project
    Environment = var.environment
  }
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# ---------------------------------------------------------------------------
# Alarm 1: High Dead-Letter / Rejected Products Count
# Triggers when WmsProductsRejected crosses the configured threshold within
# a single metric period (1 hour covers one daily run).
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "high_dlq_count" {
  alarm_name          = "${local.name_prefix}-high-rejected-products"
  alarm_description   = "Fires when WmsProductsRejected exceeds ${var.rejected_products_threshold} in one sync run."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "WmsProductsRejected"
  namespace           = var.metric_namespace
  period              = 3600  # 1 hour — covers the full daily run window
  statistic           = "Sum"
  threshold           = var.rejected_products_threshold
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alarms.arn]
  ok_actions    = [aws_sns_topic.alarms.arn]

  tags = {
    Project     = var.project
    Environment = var.environment
  }
}

# ---------------------------------------------------------------------------
# Alarm 2: Ambiguous Timeout Alert
# Fires immediately when any batch enters AMBIGUOUS_TIMEOUT state.
# Post-send read timeouts represent data-integrity uncertainty; even a single
# occurrence warrants operator review.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "ambiguous_timeout_alert" {
  alarm_name          = "${local.name_prefix}-ambiguous-timeouts"
  alarm_description   = "Fires when WmsAmbiguousTimeouts > ${var.ambiguous_timeout_threshold}. Operator review required."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "WmsAmbiguousTimeouts"
  namespace           = var.metric_namespace
  period              = 3600
  statistic           = "Sum"
  threshold           = var.ambiguous_timeout_threshold
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alarms.arn]
  ok_actions    = [aws_sns_topic.alarms.arn]

  tags = {
    Project     = var.project
    Environment = var.environment
  }
}

# ---------------------------------------------------------------------------
# Alarm 3: ECS Task Duration SLA Breach
# Monitors the ECS service using the built-in AWS/ECS metric
# "RunningTaskCount" as a proxy: if the task is still running after
# run_duration_threshold_seconds, it means the job has not completed
# within SLA.
#
# This uses a CloudWatch Logs Metric Filter on the structured JSON log line
# that the coordinator writes at run start/completion, which is the most
# precise approach for Fargate tasks (ECS does not natively emit duration).
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_metric_filter" "run_started" {
  name           = "${local.name_prefix}-run-started"
  log_group_name = var.log_group_name
  pattern        = "{ $.message = \"run_started\" }"

  metric_transformation {
    name          = "SyncRunStarted"
    namespace     = var.metric_namespace
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_log_metric_filter" "run_completed" {
  name           = "${local.name_prefix}-run-completed"
  log_group_name = var.log_group_name
  pattern        = "{ $.message = \"run_completed\" || $.message = \"run_failed\" }"

  metric_transformation {
    name          = "SyncRunCompleted"
    namespace     = var.metric_namespace
    value         = "1"
    default_value = "0"
  }
}

# Alert if the running task count stays > 0 for too long after the expected
# completion window.  Uses ECS built-in metric; simpler than duration math
# and catches hung tasks.
resource "aws_cloudwatch_metric_alarm" "sla_breach" {
  alarm_name          = "${local.name_prefix}-sla-breach"
  alarm_description   = "ECS sync task still running after ${var.run_duration_threshold_seconds}s — SLA breach risk."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "RunningTaskCount"
  namespace           = "AWS/ECS"
  period              = var.run_duration_threshold_seconds
  statistic           = "Maximum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  dimensions = {
    ClusterName = local.name_prefix
    ServiceName = local.name_prefix
  }

  alarm_actions = [aws_sns_topic.alarms.arn]
  ok_actions    = [aws_sns_topic.alarms.arn]

  tags = {
    Project     = var.project
    Environment = var.environment
  }
}

# ---------------------------------------------------------------------------
# CloudWatch Dashboard — "Sync Overview"
# Single pane of glass showing all key metrics for one daily run.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_dashboard" "sync_overview" {
  dashboard_name = "${local.name_prefix}-overview"

  dashboard_body = jsonencode({
    widgets = [
      # ---- Row 1: Throughput metrics ----------------------------------------
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 8
        height = 6
        properties = {
          title   = "Products Accepted vs Rejected"
          view    = "timeSeries"
          stacked = false
          stat    = "Sum"
          period  = 300
          metrics = [
            [var.metric_namespace, "WmsProductsAccepted", { label = "Accepted", color = "#2ca02c" }],
            [var.metric_namespace, "WmsProductsRejected", { label = "Rejected", color = "#d62728" }],
          ]
          region = "ap-south-1"
        }
      },
      {
        type   = "metric"
        x      = 8
        y      = 0
        width  = 8
        height = 6
        properties = {
          title   = "Ambiguous Timeouts (Quarantined Batches)"
          view    = "timeSeries"
          stacked = false
          stat    = "Sum"
          period  = 300
          metrics = [
            [var.metric_namespace, "WmsAmbiguousTimeouts", { label = "Ambiguous Timeouts", color = "#ff7f0e" }],
          ]
          region = "ap-south-1"
        }
      },
      {
        type   = "metric"
        x      = 16
        y      = 0
        width  = 8
        height = 6
        properties = {
          title   = "Sync Run Events"
          view    = "timeSeries"
          stacked = false
          stat    = "Sum"
          period  = 3600
          metrics = [
            [var.metric_namespace, "SyncRunStarted",   { label = "Run Started",   color = "#1f77b4" }],
            [var.metric_namespace, "SyncRunCompleted", { label = "Run Completed", color = "#2ca02c" }],
          ]
          region = "ap-south-1"
        }
      },
      # ---- Row 2: ECS infrastructure metrics --------------------------------
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title   = "ECS Task CPU Utilization (%)"
          view    = "timeSeries"
          stacked = false
          stat    = "Average"
          period  = 60
          metrics = [
            ["AWS/ECS", "CPUUtilization", "ClusterName", local.name_prefix, { label = "CPU %" }],
          ]
          region = "ap-south-1"
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          title   = "ECS Task Memory Utilization (%)"
          view    = "timeSeries"
          stacked = false
          stat    = "Average"
          period  = 60
          metrics = [
            ["AWS/ECS", "MemoryUtilization", "ClusterName", local.name_prefix, { label = "Memory %" }],
          ]
          region = "ap-south-1"
        }
      },
      # ---- Row 3: Log Insights query widget ---------------------------------
      {
        type   = "log"
        x      = 0
        y      = 12
        width  = 24
        height = 6
        properties = {
          title   = "Recent Sync Log Events (Errors & Warnings)"
          view    = "table"
          query   = "SOURCE '${var.log_group_name}' | fields @timestamp, level, component, message | filter level in ['ERROR', 'WARNING'] | sort @timestamp desc | limit 50"
          region  = "ap-south-1"
        }
      },
      # ---- Row 4: Alarm status widget ---------------------------------------
      {
        type   = "alarm"
        x      = 0
        y      = 18
        width  = 24
        height = 4
        properties = {
          title  = "Alarm Status"
          alarms = [
            aws_cloudwatch_metric_alarm.high_dlq_count.arn,
            aws_cloudwatch_metric_alarm.ambiguous_timeout_alert.arn,
            aws_cloudwatch_metric_alarm.sla_breach.arn,
          ]
        }
      },
    ]
  })
}
