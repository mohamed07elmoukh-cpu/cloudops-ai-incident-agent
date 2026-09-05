provider "aws" {
  region = var.aws_region
}

locals {
  common_tags = merge(
    {
      Application = "cloudops-ai-incident-agent"
      ManagedBy   = "terraform"
    },
    var.tags,
  )
}

resource "aws_sqs_queue" "consumer_dlq" {
  name                      = "${var.name_prefix}-incidents-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
  tags                      = local.common_tags
}

resource "aws_sqs_queue" "incidents" {
  name                       = "${var.name_prefix}-incidents"
  visibility_timeout_seconds = 60
  message_retention_seconds  = var.message_retention_seconds
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.consumer_dlq.arn
    maxReceiveCount     = 5
  })
  tags = local.common_tags
}

resource "aws_sqs_queue_redrive_allow_policy" "incidents" {
  queue_url = aws_sqs_queue.consumer_dlq.id
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.incidents.arn]
  })
}

resource "aws_sqs_queue" "eventbridge_dlq" {
  name                      = "${var.name_prefix}-eventbridge-delivery-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
  tags                      = local.common_tags
}

resource "aws_cloudwatch_event_rule" "cloudwatch_alarm" {
  name        = "${var.name_prefix}-cloudwatch-alarm-to-incidents"
  description = "Forward managed CloudWatch ALARM transitions to the CloudOps incident queue."

  event_pattern = jsonencode({
    source      = ["aws.cloudwatch"]
    detail-type = ["CloudWatch Alarm State Change"]
    detail = {
      alarmName = [{ prefix = var.alarm_name_prefix }]
      state = {
        value = ["ALARM"]
      }
    }
  })

  tags = local.common_tags
}

resource "aws_cloudwatch_event_target" "incident_queue" {
  rule = aws_cloudwatch_event_rule.cloudwatch_alarm.name
  arn  = aws_sqs_queue.incidents.arn

  dead_letter_config {
    arn = aws_sqs_queue.eventbridge_dlq.arn
  }

  retry_policy {
    maximum_event_age_in_seconds = 86400
    maximum_retry_attempts       = 185
  }
}

data "aws_iam_policy_document" "eventbridge_to_incidents" {
  statement {
    sid     = "AllowEventBridgeRule"
    effect  = "Allow"
    actions = ["sqs:SendMessage"]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    resources = [aws_sqs_queue.incidents.arn]

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.cloudwatch_alarm.arn]
    }
  }
}

resource "aws_sqs_queue_policy" "eventbridge_to_incidents" {
  queue_url = aws_sqs_queue.incidents.id
  policy    = data.aws_iam_policy_document.eventbridge_to_incidents.json
}

data "aws_iam_policy_document" "eventbridge_delivery_dlq" {
  statement {
    sid     = "AllowEventBridgeDeliveryFailures"
    effect  = "Allow"
    actions = ["sqs:SendMessage"]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    resources = [aws_sqs_queue.eventbridge_dlq.arn]

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.cloudwatch_alarm.arn]
    }
  }
}

resource "aws_sqs_queue_policy" "eventbridge_delivery_dlq" {
  queue_url = aws_sqs_queue.eventbridge_dlq.id
  policy    = data.aws_iam_policy_document.eventbridge_delivery_dlq.json
}

data "aws_iam_policy_document" "worker_queue" {
  statement {
    sid = "ConsumeIncidentMessages"
    actions = [
      "sqs:ChangeMessageVisibility",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "sqs:ReceiveMessage",
    ]
    resources = [aws_sqs_queue.incidents.arn]
  }
}

resource "aws_iam_policy" "worker_queue" {
  name        = "${var.name_prefix}-incident-worker-sqs"
  description = "Least-privilege access for the CloudOps incident worker."
  policy      = data.aws_iam_policy_document.worker_queue.json
  tags        = local.common_tags
}

resource "aws_iam_role_policy_attachment" "worker_queue" {
  count      = var.worker_role_name == null ? 0 : 1
  role       = var.worker_role_name
  policy_arn = aws_iam_policy.worker_queue.arn
}
