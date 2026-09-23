variable "project_name" {
  description = "Short project identifier used in names and tags."
  type        = string
  default     = "cloudward"
}

variable "environment" {
  description = "Environment identifier."
  type        = string
  default     = "aws-eu-north-1"
}

variable "aws_region" {
  description = "Single AWS region for Part 4."
  type        = string
  default     = "eu-north-1"
  validation {
    condition     = var.aws_region == "eu-north-1"
    error_message = "CloudWard Part 4 is intentionally scoped to eu-north-1."
  }
}

variable "kubernetes_version" {
  description = "Central EKS Kubernetes version. Version 1.35 was in standard support when selected; recheck before plan."
  type        = string
  default     = "1.35"
}

variable "vpc_cidr" {
  type        = string
  description = "VPC CIDR."
  default     = "10.42.0.0/20"
}

variable "public_subnet_cidrs" {
  type        = list(string)
  description = "Two node/ALB public egress subnet CIDRs."
  default     = ["10.42.0.0/24", "10.42.1.0/24"]
}

variable "isolated_subnet_cidrs" {
  type        = list(string)
  description = "Two future-use isolated subnet CIDRs with no Internet route."
  default     = ["10.42.8.0/24", "10.42.9.0/24"]
}

variable "allowed_eks_public_access_cidrs" {
  description = "Current operator/CI egress CIDRs. Open and documentation-only ranges are rejected."
  type        = list(string)

  validation {
    condition = length(var.allowed_eks_public_access_cidrs) > 0 && alltrue([
      for cidr in var.allowed_eks_public_access_cidrs :
      can(cidrnetmask(cidr)) &&
      !contains(["0.0.0.0/0", "::/0", "203.0.113.10/32"], cidr)
    ])
    error_message = "Replace the example with valid restricted operator/CI CIDRs; open and documentation ranges are forbidden."
  }
}

variable "administrator_principal_arns" {
  description = "Explicit operator/CI IAM role ARNs receiving EKS cluster-admin."
  type        = set(string)
  validation {
    condition = length(var.administrator_principal_arns) > 0 && alltrue([
      for arn in var.administrator_principal_arns : startswith(arn, "arn:") && !strcontains(arn, "REPLACE")
    ])
    error_message = "Provide at least one real IAM principal ARN and remove every REPLACE placeholder."
  }
}

variable "iam_permissions_boundary_arn" {
  description = "Optional organization permissions boundary for created IAM roles."
  type        = string
  default     = null
}

variable "system_node_instance_types" {
  description = "Small AL2023 On-Demand instance types verified available in eu-north-1 before planning."
  type        = list(string)
}

variable "control_plane_instance_type" {
  description = "AL2023 EC2 size for the Docker Compose control plane."
  type        = string
}

variable "karpenter_chart_version" {
  description = "Reviewed Karpenter v1 chart version compatible with EKS 1.35."
  type        = string
}

variable "eks_addon_versions" {
  description = "Optional reviewed managed add-on versions. Empty resolves compatible versions at plan time."
  type        = map(string)
  default     = {}
}

variable "ebs_csi_addon_version" {
  description = "Optional reviewed EBS CSI add-on version."
  type        = string
  default     = null
}

variable "cloudflare_ipv4_cidrs" {
  description = "Current Cloudflare origin IPv4 ranges. Empty makes the origin private from the Internet."
  type        = set(string)
  default     = []
}

variable "cloudflare_ipv6_cidrs" {
  description = "Current Cloudflare origin IPv6 ranges. Empty makes the origin private from IPv6."
  type        = set(string)
  default     = []
}

variable "monthly_budget_usd" {
  description = "AWS monthly budget alert threshold; this is not a hard service limit."
  type        = number
  default     = 50
}

variable "budget_alert_email_addresses" {
  description = "Budget notification recipients. Empty creates no notification subscribers."
  type        = set(string)
  default     = []
}

variable "tags" {
  description = "Additional non-secret resource tags."
  type        = map(string)
  default = {
    Owner      = "CloudWard"
    Lifecycle  = "ephemeral"
    CostCenter = "portfolio"
  }
}
