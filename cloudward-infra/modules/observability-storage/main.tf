locals {
  oidc_hostpath = trimsuffix(trimprefix(var.oidc_provider_url, "https://"), "/")
}

data "aws_iam_policy_document" "ebs_csi_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_hostpath}:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_hostpath}:sub"
      values   = ["system:serviceaccount:kube-system:ebs-csi-controller-sa"]
    }
  }
}

resource "aws_iam_role" "ebs_csi" {
  name                 = "${var.cluster_name}-ebs-csi"
  assume_role_policy   = data.aws_iam_policy_document.ebs_csi_assume.json
  permissions_boundary = var.permissions_boundary_arn
  tags                 = var.tags
}

resource "aws_iam_role_policy_attachment" "ebs_csi" {
  role       = aws_iam_role.ebs_csi.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}

resource "aws_eks_addon" "ebs_csi" {
  cluster_name                = var.cluster_name
  addon_name                  = "aws-ebs-csi-driver"
  addon_version               = var.ebs_csi_addon_version
  most_recent                 = var.ebs_csi_addon_version == null
  service_account_role_arn    = aws_iam_role.ebs_csi.arn
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "PRESERVE"
  tags                        = var.tags

  depends_on = [aws_iam_role_policy_attachment.ebs_csi]
}

resource "helm_release" "storage_class" {
  name      = "cloudward-observability-storage"
  namespace = "kube-system"
  chart     = "${path.module}/chart"

  values = [yamlencode({
    storageClass = {
      name = var.storage_class_name
    }
  })]

  atomic          = true
  cleanup_on_fail = true
  wait            = true

  depends_on = [aws_eks_addon.ebs_csi]
}
