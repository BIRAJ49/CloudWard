resource "aws_security_group" "control_plane" {
  name_prefix = "${var.name}-control-plane-"
  description = "Cloudflare-only HTTPS origin; no SSH"
  vpc_id      = var.vpc_id

  tags = merge(var.tags, { Name = "${var.name}-control-plane" })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "control_plane_https_ipv4" {
  for_each = var.cloudflare_ipv4_cidrs

  security_group_id = aws_security_group.control_plane.id
  description       = "HTTPS from a configured Cloudflare IPv4 range"
  cidr_ipv4         = each.value
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_ingress_rule" "control_plane_https_ipv6" {
  for_each = var.cloudflare_ipv6_cidrs

  security_group_id = aws_security_group.control_plane.id
  description       = "HTTPS from a configured Cloudflare IPv6 range"
  cidr_ipv6         = each.value
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_egress_rule" "control_plane_vpc" {
  security_group_id = aws_security_group.control_plane.id
  description       = "Internal control-plane and EKS traffic"
  cidr_ipv4         = var.vpc_cidr
  ip_protocol       = "-1"
}

resource "aws_vpc_security_group_egress_rule" "control_plane_https" {
  security_group_id = aws_security_group.control_plane.id
  description       = "TLS for SSM, GHCR, GitHub, OpenRouter, and package sources"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_egress_rule" "control_plane_dns_udp" {
  security_group_id = aws_security_group.control_plane.id
  description       = "DNS through the VPC resolver"
  cidr_ipv4         = var.vpc_cidr
  ip_protocol       = "udp"
  from_port         = 53
  to_port           = 53
}

resource "aws_vpc_security_group_egress_rule" "control_plane_dns_tcp" {
  security_group_id = aws_security_group.control_plane.id
  description       = "DNS fallback through the VPC resolver"
  cidr_ipv4         = var.vpc_cidr
  ip_protocol       = "tcp"
  from_port         = 53
  to_port           = 53
}

resource "aws_security_group" "eks_endpoint" {
  name_prefix = "${var.name}-eks-endpoint-"
  description = "Additional EKS control-plane endpoint access"
  vpc_id      = var.vpc_id
  tags        = merge(var.tags, { Name = "${var.name}-eks-endpoint" })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "eks_from_cloudward" {
  security_group_id            = aws_security_group.eks_endpoint.id
  description                  = "Kubernetes API from CloudWard EC2"
  referenced_security_group_id = aws_security_group.control_plane.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}

resource "aws_vpc_security_group_egress_rule" "eks_to_vpc" {
  security_group_id = aws_security_group.eks_endpoint.id
  description       = "EKS control-plane return traffic within the VPC"
  cidr_ipv4         = var.vpc_cidr
  ip_protocol       = "-1"
}

resource "aws_security_group" "karpenter_nodes" {
  name_prefix = "${var.name}-karpenter-node-"
  description = "Karpenter nodes; no inbound Internet access"
  vpc_id      = var.vpc_id

  tags = merge(var.tags, {
    Name                     = "${var.name}-karpenter-node"
    "karpenter.sh/discovery" = var.cluster_name
    "elbv2.k8s.aws/cluster"  = var.cluster_name
  })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "karpenter_self" {
  security_group_id            = aws_security_group.karpenter_nodes.id
  description                  = "Node-to-node and pod traffic within the node security group"
  referenced_security_group_id = aws_security_group.karpenter_nodes.id
  ip_protocol                  = "-1"
}

resource "aws_vpc_security_group_egress_rule" "karpenter_vpc" {
  security_group_id = aws_security_group.karpenter_nodes.id
  description       = "Cluster, node, pod, and VPC resolver traffic"
  cidr_ipv4         = var.vpc_cidr
  ip_protocol       = "-1"
}

resource "aws_vpc_security_group_egress_rule" "karpenter_https" {
  security_group_id = aws_security_group.karpenter_nodes.id
  description       = "TLS egress for GHCR and AWS public APIs without NAT"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_egress_rule" "karpenter_dns_udp" {
  security_group_id = aws_security_group.karpenter_nodes.id
  description       = "DNS through the VPC resolver"
  cidr_ipv4         = var.vpc_cidr
  ip_protocol       = "udp"
  from_port         = 53
  to_port           = 53
}

resource "aws_vpc_security_group_egress_rule" "karpenter_dns_tcp" {
  security_group_id = aws_security_group.karpenter_nodes.id
  description       = "DNS fallback through the VPC resolver"
  cidr_ipv4         = var.vpc_cidr
  ip_protocol       = "tcp"
  from_port         = 53
  to_port           = 53
}
