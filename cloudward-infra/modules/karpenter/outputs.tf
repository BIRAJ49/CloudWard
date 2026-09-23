output "controller_role_arn" {
  value = aws_iam_role.controller.arn
}

output "node_role_arn" {
  value = aws_iam_role.node.arn
}

output "node_role_name" {
  value = aws_iam_role.node.name
}

output "interruption_queue_name" {
  value = aws_sqs_queue.interruption.name
}

output "node_pool_names" {
  value = ["critical-ondemand", "demo-spot", "demo-ondemand-fallback"]
}
