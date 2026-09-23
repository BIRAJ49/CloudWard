output "instance_id" {
  value = aws_instance.this.id
}

output "private_ip" {
  value = aws_instance.this.private_ip
}

output "public_ip" {
  value = aws_instance.this.public_ip
}

output "ssm_start_session_command" {
  description = "Operator command template; Terraform does not execute it."
  value       = "aws ssm start-session --target ${aws_instance.this.id}"
}
