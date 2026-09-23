variable "name" {
  description = "Budget name."
  type        = string
}

variable "monthly_limit_usd" {
  description = "Monthly portfolio budget threshold in USD."
  type        = number
  default     = 50
  validation {
    condition     = var.monthly_limit_usd > 0
    error_message = "monthly_limit_usd must be positive."
  }
}

variable "alert_email_addresses" {
  description = "Verified recipients for budget alerts; empty creates the budget without email notifications."
  type        = set(string)
  default     = []
}

variable "tags" {
  description = "Additional tags."
  type        = map(string)
  default     = {}
}
