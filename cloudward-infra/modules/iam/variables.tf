variable "name" {
  description = "Resource name prefix."
  type        = string
}

variable "cluster_arn" {
  description = "Expected EKS cluster ARN used to scope control-plane access."
  type        = string
}

variable "vpc_arn" {
  description = "CloudWard VPC ARN used to scope load-balancer security-group creation."
  type        = string
}

variable "permissions_boundary_arn" {
  description = "Optional IAM permissions boundary for all created roles."
  type        = string
  default     = null
}

variable "tags" {
  description = "Additional tags."
  type        = map(string)
  default     = {}
}
