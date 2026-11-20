# Off by default (enable_rds = false). Prefer Postgres in Docker on the EC2
# host so the ~$20 Explore credit lasts for the class demo.

resource "random_password" "rds" {
  count   = var.enable_rds ? 1 : 0
  length  = 24
  special = false
}

resource "aws_db_subnet_group" "radar" {
  count      = var.enable_rds ? 1 : 0
  name       = "${var.project_prefix}-db"
  subnet_ids = data.aws_subnets.default[0].ids

  tags = {
    Name = "${var.project_prefix}-db"
  }
}

data "aws_subnets" "default" {
  count = var.enable_rds ? 1 : 0

  filter {
    name   = "vpc-id"
    values = [var.vpc_id]
  }
}

resource "aws_db_instance" "radar" {
  count = var.enable_rds ? 1 : 0

  identifier     = "${var.project_prefix}-db"
  engine         = "postgres"
  engine_version = "16"
  instance_class = "db.t4g.micro"

  allocated_storage     = 20
  max_allocated_storage = 20
  storage_type          = "gp3"

  db_name  = "ticker_alert_db"
  username = "radar"
  password = random_password.rds[0].result

  db_subnet_group_name   = aws_db_subnet_group.radar[0].name
  vpc_security_group_ids = [aws_security_group.rds[0].id]

  publicly_accessible                 = false
  multi_az                            = false
  deletion_protection                 = false
  skip_final_snapshot                 = true
  backup_retention_period             = 0
  performance_insights_enabled        = false
  auto_minor_version_upgrade          = true
  iam_database_authentication_enabled = false

  tags = {
    Name = "${var.project_prefix}-db"
  }
}

resource "aws_secretsmanager_secret" "rds" {
  count       = var.enable_rds ? 1 : 0
  name        = "${var.project_prefix}/rds"
  description = "RDS credentials for Market Radar demo"
}

resource "aws_secretsmanager_secret_version" "rds" {
  count     = var.enable_rds ? 1 : 0
  secret_id = aws_secretsmanager_secret.rds[0].id
  secret_string = jsonencode({
    username = "radar"
    password = random_password.rds[0].result
    host     = aws_db_instance.radar[0].address
    port     = aws_db_instance.radar[0].port
    dbname   = "ticker_alert_db"
    engine   = "postgres"
  })
}
