output "region" {
  value = var.aws_region
}

output "vpc_id" {
  value = module.network.vpc_id
}

output "public_subnet_ids" {
  value = module.network.public_subnet_ids
}

output "isolated_subnet_ids" {
  value = module.network.isolated_subnet_ids
}

output "eks_cluster_name" {
  value = module.eks.cluster_name
}

output "eks_cluster_arn" {
  value = module.eks.cluster_arn
}

output "eks_endpoint" {
  value     = module.eks.cluster_endpoint
  sensitive = true
}

output "cloudward_kubernetes_group" {
  value = "cloudward:executor"
}

output "system_node_group_name" {
  value = module.eks.system_node_group_name
}

output "karpenter_node_pool_names" {
  value = module.karpenter.node_pool_names
}

output "control_plane_instance_id" {
  value = module.control_plane_ec2.instance_id
}

output "control_plane_public_ip" {
  description = "Cloudflare DNS origin; direct ingress is restricted to configured Cloudflare ranges."
  value       = module.control_plane_ec2.public_ip
}

output "control_plane_ssm_command" {
  value = module.control_plane_ec2.ssm_start_session_command
}

output "observability_storage_class" {
  value = module.observability_storage.storage_class_name
}

output "observability_pvc_limits_gib" {
  value = module.observability_storage.recommended_pvc_limits_gib
}

output "budget_id" {
  value = module.budget.budget_id
}

output "public_exposure_summary" {
  value = {
    eks_api = {
      public_enabled  = true
      allowed_cidrs   = var.allowed_eks_public_access_cidrs
      private_enabled = true
    }
    control_plane = {
      public_ipv4    = true
      ingress        = "TCP/443 from configured Cloudflare CIDRs only"
      ssh            = false
      administration = "AWS Systems Manager"
    }
    eks_nodes = {
      public_ipv4 = true
      ingress     = "No Internet ingress; EKS/VPC security-group sources only"
      reason      = "Cost-conscious no-NAT portfolio trade-off"
    }
  }
}
