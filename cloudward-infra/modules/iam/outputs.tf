output "eks_cluster_role_arn" {
  value = aws_iam_role.eks_cluster.arn
}

output "eks_node_role_arn" {
  value = aws_iam_role.eks_nodes.arn
}

output "control_plane_role_arn" {
  value = aws_iam_role.control_plane.arn
}

output "control_plane_role_name" {
  value = aws_iam_role.control_plane.name
}

output "control_plane_instance_profile_name" {
  value = aws_iam_instance_profile.control_plane.name
}

output "load_balancer_controller_role_arn" {
  value = aws_iam_role.load_balancer_controller.arn
}
