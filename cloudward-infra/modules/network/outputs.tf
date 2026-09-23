output "vpc_id" {
  value = aws_vpc.this.id
}

output "vpc_arn" {
  value = aws_vpc.this.arn
}

output "vpc_cidr" {
  value = aws_vpc.this.cidr_block
}

output "public_subnet_ids" {
  value = [for az in var.availability_zones : aws_subnet.public[az].id]
}

output "isolated_subnet_ids" {
  value = [for az in var.availability_zones : aws_subnet.isolated[az].id]
}

output "availability_zones" {
  value = var.availability_zones
}
