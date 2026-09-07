output "incident_queue_url" {
  description = "Set this value as INCIDENT_QUEUE_URL on the incident worker."
  value       = aws_sqs_queue.incidents.url
}

output "incident_queue_arn" {
  value = aws_sqs_queue.incidents.arn
}

output "consumer_dlq_url" {
  value = aws_sqs_queue.consumer_dlq.url
}

output "eventbridge_delivery_dlq_url" {
  value = aws_sqs_queue.eventbridge_dlq.url
}

output "eventbridge_rule_arn" {
  value = aws_cloudwatch_event_rule.cloudwatch_alarm.arn
}

output "worker_policy_arn" {
  description = "Attach this policy to the incident worker role if worker_role_name was omitted."
  value       = aws_iam_policy.worker_queue.arn
}

output "pricing_estimator_policy_arn" {
  description = "Attach this policy to the API metrics/remediation role if remediation_role_name was omitted."
  value       = aws_iam_policy.pricing_estimator.arn
}
