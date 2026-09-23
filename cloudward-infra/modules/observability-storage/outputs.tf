output "ebs_csi_role_arn" {
  value = aws_iam_role.ebs_csi.arn
}

output "storage_class_name" {
  value = var.storage_class_name
}

output "retention_days" {
  value = var.retention_days
}

output "recommended_pvc_limits_gib" {
  description = "Guardrails for the GitOps values; Terraform does not own observability PVCs."
  value = {
    prometheus = 20
    loki       = 20
    tempo      = 10
    grafana    = 5
  }
}
