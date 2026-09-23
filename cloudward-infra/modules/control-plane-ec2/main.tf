data "aws_ssm_parameter" "al2023_ami" {
  name = var.ami_ssm_parameter
}

resource "aws_instance" "this" {
  ami                         = data.aws_ssm_parameter.al2023_ami.value
  instance_type               = var.instance_type
  subnet_id                   = var.subnet_id
  vpc_security_group_ids      = var.security_group_ids
  associate_public_ip_address = true
  iam_instance_profile        = var.iam_instance_profile_name

  # Deliberately no key_name and no port 22 rule. Use SSM Session Manager.
  user_data                   = file("${path.module}/user-data.sh")
  user_data_replace_on_change = true

  metadata_options {
    http_endpoint               = "enabled"
    http_protocol_ipv6          = "disabled"
    http_put_response_hop_limit = var.metadata_hop_limit
    http_tokens                 = "required"
    instance_metadata_tags      = "enabled"
  }

  root_block_device {
    delete_on_termination = true
    encrypted             = true
    volume_type           = "gp3"
    volume_size           = var.root_volume_size_gib
    iops                  = 3000
    throughput            = 125
    tags                  = merge(var.tags, { Name = "${var.name}-root" })
  }

  credit_specification {
    cpu_credits = "standard"
  }

  monitoring                           = false
  source_dest_check                    = true
  disable_api_stop                     = false
  disable_api_termination              = false
  instance_initiated_shutdown_behavior = "stop"

  tags = merge(var.tags, {
    Name = var.name
    Role = "cloudward-control-plane"
  })
}
