terraform {
  required_version = ">= 1.10.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
  }

  # Bootstrap state remains local because this configuration creates the S3
  # backend. Protect this file separately after the one-time bootstrap.
  backend "local" {
    path = "terraform.tfstate"
  }
}
