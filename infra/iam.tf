data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ec2" {
  name               = "${var.project_prefix}-ec2"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

data "aws_iam_policy_document" "ec2_app" {
  statement {
    sid = "LakeReadWrite"
    actions = [
      "s3:ListBucket",
      "s3:GetBucketLocation",
    ]
    resources = [aws_s3_bucket.lake.arn]
  }

  statement {
    sid = "LakeObjects"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts",
    ]
    resources = ["${aws_s3_bucket.lake.arn}/*"]
  }

  statement {
    sid = "ReadAlpacaSecret"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret",
    ]
    resources = [
      data.aws_secretsmanager_secret.alpaca.arn,
    ]
  }

  dynamic "statement" {
    for_each = var.enable_rds ? [1] : []
    content {
      sid = "ReadRdsSecret"
      actions = [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret",
      ]
      resources = [aws_secretsmanager_secret.rds[0].arn]
    }
  }
}

data "aws_secretsmanager_secret" "alpaca" {
  name = var.alpaca_secret_name
}

resource "aws_iam_role_policy" "ec2_app" {
  name   = "${var.project_prefix}-ec2-app"
  role   = aws_iam_role.ec2.id
  policy = data.aws_iam_policy_document.ec2_app.json
}

resource "aws_iam_instance_profile" "ec2" {
  name = "${var.project_prefix}-ec2"
  role = aws_iam_role.ec2.name
}

# Attach the instance profile to the already-running Explore/demo EC2.
resource "null_resource" "associate_instance_profile" {
  triggers = {
    instance_id = var.ec2_instance_id
    profile_arn = aws_iam_instance_profile.ec2.arn
  }

  depends_on = [aws_iam_instance_profile.ec2]

  provisioner "local-exec" {
    interpreter = ["/bin/bash", "-c"]
    command     = <<-EOT
      set -euo pipefail
      PROFILE='${aws_iam_instance_profile.ec2.name}'
      # IAM instance profiles can lag briefly after create.
      for i in 1 2 3 4 5 6; do
        if aws iam get-instance-profile --instance-profile-name "$PROFILE" >/dev/null 2>&1; then
          break
        fi
        sleep 5
      done
      EXISTING="$(aws ec2 describe-iam-instance-profile-associations \
        --region '${var.aws_region}' \
        --filters Name=instance-id,Values='${var.ec2_instance_id}' \
        --query 'IamInstanceProfileAssociations[0].AssociationId' \
        --output text 2>/dev/null || true)"
      if [[ "$EXISTING" == "None" || -z "$EXISTING" ]]; then
        for i in 1 2 3 4 5 6; do
          if aws ec2 associate-iam-instance-profile \
            --region '${var.aws_region}' \
            --instance-id '${var.ec2_instance_id}' \
            --iam-instance-profile Name="$PROFILE"; then
            exit 0
          fi
          sleep 5
        done
        exit 1
      fi
      CURRENT="$(aws ec2 describe-iam-instance-profile-associations \
        --region '${var.aws_region}' \
        --association-ids "$EXISTING" \
        --query 'IamInstanceProfileAssociations[0].IamInstanceProfile.Arn' \
        --output text)"
      if [[ "$CURRENT" == *"$PROFILE"* ]]; then
        echo "Instance profile already associated: $CURRENT"
        exit 0
      fi
      aws ec2 replace-iam-instance-profile-association \
        --region '${var.aws_region}' \
        --association-id "$EXISTING" \
        --iam-instance-profile Name="$PROFILE"
    EOT
  }
}
