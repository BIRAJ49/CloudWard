variable "cluster_name" {
  type        = string
  description = "EKS cluster name."
}

variable "oidc_provider_arn" {
  type        = string
  description = "Cluster IAM OIDC provider ARN."
}

variable "oidc_provider_url" {
  type        = string
  description = "Cluster IAM OIDC provider URL."
}

variable "permissions_boundary_arn" {
  type        = string
  description = "Optional IAM permissions boundary."
  default     = null
}

variable "ebs_csi_addon_version" {
  type        = string
  description = "Optional reviewed EBS CSI add-on version; null selects the compatible version during planning."
  default     = null
}

variable "storage_class_name" {
  type        = string
  description = "Encrypted gp3 StorageClass name used by observability GitOps manifests."
  default     = "cloudward-observability-gp3"
}

variable "retention_days" {
  type        = number
  description = "Documented maximum observability retention for this portfolio environment."
  default     = 7
  validation {
    condition     = var.retention_days > 0 && var.retention_days <= 7
    error_message = "Portfolio observability retention must be between 1 and 7 days."
  }
}

variable "tags" {
  type        = map(string)
  description = "Additional tags."
  default     = {}
}
