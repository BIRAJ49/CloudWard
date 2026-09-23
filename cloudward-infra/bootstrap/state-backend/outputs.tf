output "bucket_name" {
  description = "S3 backend bucket name."
  value       = aws_s3_bucket.state.id
}

output "bucket_arn" {
  description = "S3 backend bucket ARN."
  value       = aws_s3_bucket.state.arn
}

output "state_access_policy_arn" {
  description = "Least-privilege policy to attach only to Terraform operator/CI roles."
  value       = aws_iam_policy.state_access.arn
}
