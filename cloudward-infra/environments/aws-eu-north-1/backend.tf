terraform {
  backend "s3" {
    key          = "cloudward/aws-eu-north-1/terraform.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}
