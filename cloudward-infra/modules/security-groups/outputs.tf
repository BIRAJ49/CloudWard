output "control_plane_security_group_id" {
  value = aws_security_group.control_plane.id
}

output "eks_endpoint_security_group_id" {
  value = aws_security_group.eks_endpoint.id
}

output "karpenter_node_security_group_id" {
  value = aws_security_group.karpenter_nodes.id
}
