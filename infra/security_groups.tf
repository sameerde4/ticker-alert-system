# Open the Radar UI port on the existing launch-wizard security group.
resource "aws_security_group_rule" "app_http" {
  type              = "ingress"
  description       = "Market Radar FastAPI / UI demo port"
  from_port         = var.app_port
  to_port           = var.app_port
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = var.ec2_security_group_id
}

# Optional RDS: allow Postgres only from the EC2 security group.
resource "aws_security_group" "rds" {
  count       = var.enable_rds ? 1 : 0
  name        = "${var.project_prefix}-rds"
  description = "Market Radar demo RDS"
  vpc_id      = var.vpc_id

  ingress {
    description     = "Postgres from Market Radar EC2"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [var.ec2_security_group_id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_prefix}-rds"
  }
}
