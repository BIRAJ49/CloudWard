variable "name" {
  description = "Resource name prefix."
  type        = string
}

variable "vpc_cidr" {
  description = "VPC IPv4 CIDR."
  type        = string
}

variable "availability_zones" {
  description = "Exactly two available AZ names."
  type        = list(string)
  validation {
    condition     = length(var.availability_zones) == 2
    error_message = "CloudWard v1 requires exactly two availability zones."
  }
}

variable "public_subnet_cidrs" {
  description = "Two public subnet CIDRs used by EKS nodes and the shared ALB."
  type        = list(string)
  validation {
    condition     = length(var.public_subnet_cidrs) == 2
    error_message = "Provide exactly two public subnet CIDRs."
  }
}

variable "isolated_subnet_cidrs" {
  description = "Two isolated subnet CIDRs with no default Internet route."
  type        = list(string)
  validation {
    condition     = length(var.isolated_subnet_cidrs) == 2
    error_message = "Provide exactly two isolated subnet CIDRs."
  }
}

variable "cluster_name" {
  description = "EKS cluster name used by subnet discovery tags."
  type        = string
}

variable "tags" {
  description = "Additional tags."
  type        = map(string)
  default     = {}
}
