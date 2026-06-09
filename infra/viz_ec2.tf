# Apache Superset + PostgreSQL on EC2 (Marko's slice).
#
# One EC2 instance in a public subnet (network.tf) runs PostgreSQL and Superset
# via Docker Compose. It uses Milos's `superset` and `postgres` security groups
# and reads the PostgreSQL password from the Secrets Manager placeholder. The
# gold metric schema (db/gold_metrics.sql) is applied on first boot so Superset
# has tables to chart.
#
# NOTE: the gold->PostgreSQL loader (Milos) must point POSTGRES_HOST at this
# instance (see the viz_private_dns output) and run inside the VPC/lambda SG to
# reach 5432. Superset itself talks to PostgreSQL over localhost on this host.

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-arm64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_iam_role" "viz_ec2" {
  name = "${local.name_prefix}-viz-ec2"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })

  tags = merge(local.common_tags, {
    Layer = "visualization"
  })
}

data "aws_iam_policy_document" "viz_ec2" {
  statement {
    sid       = "ReadPostgresPassword"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.postgres_password.arn]
  }
}

resource "aws_iam_role_policy" "viz_ec2" {
  name   = "${local.name_prefix}-viz-ec2"
  role   = aws_iam_role.viz_ec2.id
  policy = data.aws_iam_policy_document.viz_ec2.json
}

resource "aws_iam_instance_profile" "viz_ec2" {
  name = "${local.name_prefix}-viz-ec2"
  role = aws_iam_role.viz_ec2.name
}

resource "aws_instance" "viz" {
  ami                         = data.aws_ami.al2023.id
  instance_type               = var.superset_instance_type
  subnet_id                   = aws_subnet.public[0].id
  vpc_security_group_ids      = [aws_security_group.superset.id, aws_security_group.postgres.id]
  iam_instance_profile        = aws_iam_instance_profile.viz_ec2.name
  associate_public_ip_address = true
  key_name                    = var.ec2_key_name == "" ? null : var.ec2_key_name

  user_data = templatefile("${path.module}/templates/superset_postgres_userdata.sh.tpl", {
    aws_region          = var.aws_region
    db_name             = var.postgres_db_name
    db_user             = var.postgres_app_user
    password_secret_arn = aws_secretsmanager_secret.postgres_password.arn
    superset_admin_user = var.superset_admin_user
    gold_metrics_sql    = file("${path.module}/../db/gold_metrics.sql")
  })

  root_block_device {
    volume_size = 30
    encrypted   = true
  }

  tags = merge(local.common_tags, {
    Name  = "${local.name_prefix}-superset-postgres"
    Layer = "visualization"
  })
}

output "viz_public_ip" {
  description = "Public IP of the Superset/PostgreSQL EC2 host."
  value       = aws_instance.viz.public_ip
}

output "viz_private_dns" {
  description = "Private DNS of the EC2 host. Point the gold->PostgreSQL loader's POSTGRES_HOST here."
  value       = aws_instance.viz.private_dns
}

output "superset_url" {
  description = "Apache Superset UI URL (reachable from admin_cidr_blocks)."
  value       = "http://${aws_instance.viz.public_ip}:8088"
}
