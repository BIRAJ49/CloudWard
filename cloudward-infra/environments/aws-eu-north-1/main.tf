data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_partition" "current" {}
data "aws_caller_identity" "current" {}

locals {
  cluster_name       = "${var.project_name}-${var.environment}"
  availability_zones = slice(data.aws_availability_zones.available.names, 0, 2)
  cluster_arn        = "arn:${data.aws_partition.current.partition}:eks:${var.aws_region}:${data.aws_caller_identity.current.account_id}:cluster/${local.cluster_name}"
}

module "network" {
  source = "../../modules/network"

  name                  = "${local.cluster_name}-vpc"
  cluster_name          = local.cluster_name
  vpc_cidr              = var.vpc_cidr
  availability_zones    = local.availability_zones
  public_subnet_cidrs   = var.public_subnet_cidrs
  isolated_subnet_cidrs = var.isolated_subnet_cidrs
  tags                  = var.tags
}

module "iam" {
  source = "../../modules/iam"

  name                     = local.cluster_name
  cluster_arn              = local.cluster_arn
  vpc_arn                  = module.network.vpc_arn
  permissions_boundary_arn = var.iam_permissions_boundary_arn
  tags                     = var.tags
}

module "security_groups" {
  source = "../../modules/security-groups"

  name                  = local.cluster_name
  cluster_name          = local.cluster_name
  vpc_id                = module.network.vpc_id
  vpc_cidr              = module.network.vpc_cidr
  cloudflare_ipv4_cidrs = var.cloudflare_ipv4_cidrs
  cloudflare_ipv6_cidrs = var.cloudflare_ipv6_cidrs
  tags                  = var.tags
}

module "eks" {
  source = "../../modules/eks"

  cluster_name                          = local.cluster_name
  kubernetes_version                    = var.kubernetes_version
  cluster_role_arn                      = module.iam.eks_cluster_role_arn
  node_role_arn                         = module.iam.eks_node_role_arn
  subnet_ids                            = concat(module.network.public_subnet_ids, module.network.isolated_subnet_ids)
  system_node_subnet_ids                = module.network.public_subnet_ids
  additional_cluster_security_group_ids = [module.security_groups.eks_endpoint_security_group_id]
  public_access_cidrs                   = var.allowed_eks_public_access_cidrs
  system_node_instance_types            = var.system_node_instance_types
  control_plane_principal_arn           = module.iam.control_plane_role_arn
  load_balancer_controller_role_arn     = module.iam.load_balancer_controller_role_arn
  administrator_principal_arns          = var.administrator_principal_arns
  addon_versions                        = var.eks_addon_versions
  tags                                  = var.tags

  depends_on = [module.iam]
}

module "control_plane_ec2" {
  source = "../../modules/control-plane-ec2"

  name                      = "${local.cluster_name}-control-plane"
  subnet_id                 = module.network.public_subnet_ids[0]
  security_group_ids        = [module.security_groups.control_plane_security_group_id]
  iam_instance_profile_name = module.iam.control_plane_instance_profile_name
  instance_type             = var.control_plane_instance_type
  metadata_hop_limit        = 2
  tags                      = var.tags
}

module "observability_storage" {
  source = "../../modules/observability-storage"

  cluster_name             = module.eks.cluster_name
  oidc_provider_arn        = module.eks.oidc_provider_arn
  oidc_provider_url        = module.eks.oidc_provider_url
  permissions_boundary_arn = var.iam_permissions_boundary_arn
  ebs_csi_addon_version    = var.ebs_csi_addon_version
  retention_days           = 7
  tags                     = var.tags

  depends_on = [module.eks]
}

module "karpenter" {
  source = "../../modules/karpenter"

  cluster_name                      = module.eks.cluster_name
  cluster_arn                       = module.eks.cluster_arn
  cluster_primary_security_group_id = module.eks.cluster_primary_security_group_id
  node_security_group_id            = module.security_groups.karpenter_node_security_group_id
  chart_version                     = var.karpenter_chart_version
  permissions_boundary_arn          = var.iam_permissions_boundary_arn
  tags                              = var.tags

  depends_on = [module.eks]
}

module "budget" {
  source = "../../modules/budgets"

  name                  = "${local.cluster_name}-monthly"
  monthly_limit_usd     = var.monthly_budget_usd
  alert_email_addresses = var.budget_alert_email_addresses
  tags                  = var.tags
}
