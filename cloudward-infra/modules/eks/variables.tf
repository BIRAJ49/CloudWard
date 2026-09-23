variable "cluster_name" {
  description = "EKS cluster name."
  type        = string
}

variable "kubernetes_version" {
  description = "EKS Kubernetes minor version, centrally selected by the environment."
  type        = string
}

variable "cluster_role_arn" {
  description = "Dedicated EKS cluster IAM role ARN."
  type        = string
}

variable "node_role_arn" {
  description = "Dedicated managed system-node IAM role ARN."
  type        = string
}

variable "subnet_ids" {
  description = "Subnets used by EKS control-plane ENIs."
  type        = list(string)
}

variable "system_node_subnet_ids" {
  description = "Public egress subnets for v1 managed nodes; no NAT gateway is created."
  type        = list(string)
}

variable "additional_cluster_security_group_ids" {
  description = "Additional EKS endpoint security groups."
  type        = list(string)
  default     = []
}

variable "public_access_cidrs" {
  description = "Explicit operator CIDRs for the public EKS endpoint. Open Internet CIDRs are rejected."
  type        = list(string)

  validation {
    condition = length(var.public_access_cidrs) > 0 && alltrue([
      for cidr in var.public_access_cidrs :
      can(cidrnetmask(cidr)) && !contains(["0.0.0.0/0", "::/0"], cidr)
    ])
    error_message = "Provide valid, restricted operator CIDRs; 0.0.0.0/0 and ::/0 are forbidden."
  }
}

variable "enabled_cluster_log_types" {
  description = "Cost-bounded EKS control-plane logs."
  type        = list(string)
  default     = ["api", "audit", "authenticator"]
}

variable "log_retention_days" {
  description = "CloudWatch retention for EKS control-plane logs."
  type        = number
  default     = 7
}

variable "system_node_instance_types" {
  description = "Operator-verified instance types for the small managed system group."
  type        = list(string)
}

variable "system_node_min_size" {
  type    = number
  default = 1
}

variable "system_node_desired_size" {
  type    = number
  default = 1
}

variable "system_node_max_size" {
  type    = number
  default = 2
}

variable "system_node_volume_size_gib" {
  description = "Encrypted gp3 root volume size."
  type        = number
  default     = 30
}

variable "control_plane_principal_arn" {
  description = "CloudWard EC2 role mapped into the staging-scoped executor Kubernetes group."
  type        = string
}

variable "load_balancer_controller_role_arn" {
  description = "Dedicated AWS Load Balancer Controller Pod Identity role ARN."
  type        = string
}

variable "administrator_principal_arns" {
  description = "Explicit operator/CI roles that receive EKS cluster-admin access."
  type        = set(string)
  validation {
    condition     = length(var.administrator_principal_arns) > 0
    error_message = "At least one explicit administrator principal is required when bootstrap creator admin is disabled."
  }
}

variable "addon_versions" {
  description = "Optional reviewed add-on versions keyed by vpc-cni, kube-proxy, coredns, and eks-pod-identity-agent. Empty selects the EKS-compatible version during planning."
  type        = map(string)
  default     = {}
}

variable "tags" {
  description = "Additional tags."
  type        = map(string)
  default     = {}
}
