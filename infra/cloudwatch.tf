# Demo ops: one log group for Docker Compose services (awslogs driver on EC2).

resource "aws_cloudwatch_log_group" "demo" {
  name              = "/${var.project_prefix}/demo"
  retention_in_days = 7

  tags = {
    Name = "${var.project_prefix}-demo-logs"
  }
}
