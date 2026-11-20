variable "aws_region" {
  type        = string
  description = "AWS region for Market Radar demo resources."
  default     = "us-east-1"
}

variable "project_prefix" {
  type        = string
  description = "Name prefix for demo resources."
  default     = "market-radar"
}

variable "ec2_instance_id" {
  type        = string
  description = "Existing EC2 instance to attach the IAM instance profile to."
  default     = "i-0e437ba8984153370"
}

variable "ec2_security_group_id" {
  type        = string
  description = "Security group already on the EC2 instance (launch-wizard-1)."
  default     = "sg-0eb1f722c3ef5f541"
}

variable "app_port" {
  type        = number
  description = "Host port for the Radar FastAPI UI."
  default     = 8010
}

variable "enable_rds" {
  type        = bool
  description = "If true, create a small RDS Postgres. Default false — use Postgres on EC2 to save credits."
  default     = false
}

variable "vpc_id" {
  type        = string
  description = "VPC for optional RDS."
  default     = "vpc-000bf51c5712e4951"
}

variable "alpaca_secret_name" {
  type        = string
  description = "Secrets Manager name for Alpaca credentials."
  default     = "market-radar/alpaca"
}
