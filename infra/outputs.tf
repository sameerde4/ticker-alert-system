output "lake_bucket" {
  description = "S3 lake bucket name"
  value       = aws_s3_bucket.lake.bucket
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

output "app_url_hint" {
  description = "Open this after Docker Compose is up on the instance."
  value       = "http://34.229.198.252:${var.app_port}/ui"
}

output "rds_endpoint" {
  value       = var.enable_rds ? aws_db_instance.radar[0].address : null
  description = "RDS endpoint when enable_rds=true; otherwise use Postgres on EC2."
}

output "enable_rds" {
  value = var.enable_rds
}
