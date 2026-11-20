output "lake_bucket" {
  description = "S3 lake bucket name"
  value       = aws_s3_bucket.lake.bucket
}

output "cloudwatch_log_group" {
  description = "CloudWatch Logs group for Docker Compose (awslogs driver)."
  value       = aws_cloudwatch_log_group.demo.name
}

output "ec2_instance_id" {
  value = var.ec2_instance_id
}

output "ec2_instance_profile" {
  value = aws_iam_instance_profile.ec2.name
}

output "alpaca_secret_name" {
  value = var.alpaca_secret_name
}

data "aws_instance" "demo" {
  instance_id = var.ec2_instance_id
}

output "app_url_hint" {
  description = "Open this after Docker Compose is up on the instance."
  value       = "http://${data.aws_instance.demo.public_ip}:${var.app_port}/ui"
}

output "ec2_public_ip" {
  value = data.aws_instance.demo.public_ip
}

output "rds_endpoint" {
  value       = var.enable_rds ? aws_db_instance.radar[0].address : null
  description = "RDS endpoint when enable_rds=true; otherwise use Postgres on EC2."
}

output "enable_rds" {
  value = var.enable_rds
}
