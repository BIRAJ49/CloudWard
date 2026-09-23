variable "name" {
  description = "EC2 Name tag."
  type        = string
}

variable "subnet_id" {
  description = "Public egress subnet used for the Cloudflare origin."
  type        = string
}

variable "security_group_ids" {
  description = "Security groups; expected to allow Cloudflare HTTPS only and no SSH."
  type        = list(string)
}

variable "iam_instance_profile_name" {
  description = "SSM-enabled, least-privilege instance profile name."
  type        = string
}

variable "instance_type" {
  description = "Operator-selected instance type sized for the Compose control plane."
  type        = string
}

variable "root_volume_size_gib" {
  description = "Encrypted gp3 root disk size."
  type        = number
  default     = 40
}

variable "ami_ssm_parameter" {
  description = "AWS public SSM parameter for the AL2023 x86_64 AMI."
  type        = string
  default     = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

variable "metadata_hop_limit" {
  description = "IMDSv2 hop limit. Two permits trusted bridged Compose containers to use the EC2 role."
  type        = number
  default     = 2
  validation {
    condition     = contains([1, 2], var.metadata_hop_limit)
    error_message = "metadata_hop_limit must be 1 or 2. Use 2 only for the trusted Compose host."
  }
}

variable "tags" {
  description = "Additional tags."
  type        = map(string)
  default     = {}
}
