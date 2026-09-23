variable "aws_region" {
  description = "AWS region for the state bucket."
  type        = string
  default     = "eu-north-1"
}

variable "bucket_name" {
  description = "Globally unique S3 bucket name for Terraform state."
  type        = string

  validation {
    condition     = length(var.bucket_name) >= 3 && length(var.bucket_name) <= 63
    error_message = "bucket_name must be a valid 3-63 character S3 bucket name."
  }
}

variable "state_key_prefix" {
  description = "Only objects below this prefix are accessible through the generated state policy."
  type        = string
  default     = "cloudward/"

  validation {
    condition     = startswith(var.state_key_prefix, "cloudward/") && endswith(var.state_key_prefix, "/")
    error_message = "state_key_prefix must remain below cloudward/ and end with a slash."
  }
}

variable "state_access_role_names" {
  description = "Existing IAM role names that receive the restricted state policy. Empty is safest; attach later explicitly."
  type        = set(string)
  default     = []
}

variable "tags" {
  description = "Tags applied to bootstrap resources."
  type        = map(string)
  default = {
    Project   = "CloudWard"
    ManagedBy = "Terraform"
    Purpose   = "terraform-state"
  }
}
