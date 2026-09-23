variable "name" {
  type        = string
  description = "Resource name prefix."
}

variable "vpc_id" {
  type        = string
  description = "VPC ID."
}

variable "vpc_cidr" {
  type        = string
  description = "VPC CIDR used for internal egress."
}

variable "cluster_name" {
  type        = string
  description = "Cluster name used for Karpenter discovery."
}

variable "cloudflare_ipv4_cidrs" {
  type        = set(string)
  description = "Current Cloudflare IPv4 origin ranges allowed to TCP/443. Empty disables public origin ingress."
  default     = []
}

variable "cloudflare_ipv6_cidrs" {
  type        = set(string)
  description = "Current Cloudflare IPv6 origin ranges allowed to TCP/443. Empty disables public origin ingress."
  default     = []
}

variable "tags" {
  type        = map(string)
  description = "Additional tags."
  default     = {}
}
