variable "cluster_name" {
  type        = string
  description = "EKS cluster name and discovery-tag value."
}

variable "cluster_arn" {
  type        = string
  description = "EKS cluster ARN for scoped DescribeCluster access."
}

variable "cluster_primary_security_group_id" {
  type        = string
  description = "EKS-created cluster security group allowed to reach Karpenter nodes."
}

variable "node_security_group_id" {
  type        = string
  description = "Restricted node security group selected by EC2NodeClass."
}

variable "chart_version" {
  type        = string
  description = "Reviewed Karpenter Helm chart version compatible with the selected EKS minor."
}

variable "permissions_boundary_arn" {
  type        = string
  description = "Optional IAM permissions boundary."
  default     = null
}

variable "allowed_instance_categories" {
  type        = list(string)
  description = "Bounded Karpenter instance categories."
  default     = ["c", "m", "t"]
}

variable "allowed_instance_sizes" {
  type        = list(string)
  description = "Bounded Karpenter sizes; intentionally excludes xlarge and larger."
  default     = ["small", "medium", "large"]
}

variable "critical_cpu_limit" {
  type    = string
  default = "16"
}

variable "critical_memory_limit" {
  type    = string
  default = "64Gi"
}

variable "demo_spot_cpu_limit" {
  type    = string
  default = "16"
}

variable "demo_spot_memory_limit" {
  type    = string
  default = "64Gi"
}

variable "demo_fallback_cpu_limit" {
  type    = string
  default = "8"
}

variable "demo_fallback_memory_limit" {
  type    = string
  default = "32Gi"
}

variable "node_volume_size_gib" {
  type        = number
  description = "Encrypted gp3 root volume size for Karpenter nodes."
  default     = 30
}

variable "tags" {
  type        = map(string)
  description = "Additional AWS tags."
  default     = {}
}
