# Stable demo URL: public IPv4 that survives stop/start.
# FREE while associated with a running instance. RELEASE on teardown
# (or you pay for an idle/unattached Elastic IP).

resource "aws_eip" "demo" {
  domain = "vpc"

  tags = {
    Name = "${var.project_prefix}-demo"
  }
}

resource "aws_eip_association" "demo" {
  instance_id   = var.ec2_instance_id
  allocation_id = aws_eip.demo.id
}
