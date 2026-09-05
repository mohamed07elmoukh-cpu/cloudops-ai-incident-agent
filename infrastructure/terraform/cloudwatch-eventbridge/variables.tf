variable "aws_region" {
  description = "AWS region containing the CloudWatch alarms and SQS queues."
  type        = string
  default     = "eu-west-1"
}

variable "name_prefix" {
  description = "Prefix used for EventBridge and SQS resources."
  type        = string
  default     = "cloudops"
}

variable "alarm_name_prefix" {
  description = "Only ALARM transitions whose alarm name starts with this value are forwarded."
  type        = string
  default     = "cloudops-"

  validation {
    condition     = length(trimspace(var.alarm_name_prefix)) > 0
    error_message = "alarm_name_prefix cannot be empty."
  }
}

variable "worker_role_name" {
  description = "Optional existing IAM role name to which the SQS consumer policy is attached."
  type        = string
  default     = null
  nullable    = true
}

variable "message_retention_seconds" {
  description = "Retention period for incident messages."
  type        = number
  default     = 345600
}

variable "tags" {
  description = "Tags applied to managed resources."
  type        = map(string)
  default     = {}
}
