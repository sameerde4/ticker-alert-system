#!/usr/bin/env bash
# From a developer machine: sync repo to EC2 and bootstrap the demo stack.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTANCE_ID="${INSTANCE_ID:-i-0e437ba8984153370}"
REGION="${AWS_REGION:-us-east-1}"
REMOTE_USER="${REMOTE_USER:-ec2-user}"
REMOTE_DIR="${REMOTE_DIR:-/opt/market-radar}"

IP="$(aws ec2 describe-instances --region "$REGION" --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)"
[[ -n "$IP" && "$IP" != "None" ]] || { echo "No public IP for $INSTANCE_ID"; exit 1; }

KEY="$(mktemp -t market-radar-ssh)"
rm -f "$KEY"
PUB="${KEY}.pub"
cleanup() { rm -f "$KEY" "$PUB"; }
trap cleanup EXIT

ssh-keygen -t ed25519 -f "$KEY" -N '' -q
aws ec2-instance-connect send-ssh-public-key \
  --region "$REGION" \
  --instance-id "$INSTANCE_ID" \
  --instance-os-user "$REMOTE_USER" \
  --ssh-public-key "file://${PUB}" >/dev/null

SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)
RSYNC_SSH="ssh -i ${KEY} -o StrictHostKeyChecking=accept-new"

echo "==> Ensuring ${REMOTE_DIR} on ${IP}"
"${SSH[@]}" "${REMOTE_USER}@${IP}" "sudo mkdir -p ${REMOTE_DIR} && sudo chown ${REMOTE_USER}:${REMOTE_USER} ${REMOTE_DIR}"

echo "==> Syncing repo (excluding venvs / local lake / .git)"
rsync -az --delete \
  -e "$RSYNC_SSH" \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '**/.venv/' \
  --exclude '**/__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude '.run/' \
  --exclude '.idea/' \
  --exclude 'data/lake/raw/' \
  --exclude 'data/lake/curated/' \
  --exclude 'data/lake/registry/' \
  --exclude 'infra/.terraform/' \
  --exclude 'infra/tfplan' \
  --exclude 'infra/*.tfstate*' \
  --exclude 'deploy/alpaca.env' \
  "${ROOT}/" "${REMOTE_USER}@${IP}:${REMOTE_DIR}/"

echo "==> Bootstrapping on host"
# Instance Connect keys expire quickly — refresh before long bootstrap.
aws ec2-instance-connect send-ssh-public-key \
  --region "$REGION" \
  --instance-id "$INSTANCE_ID" \
  --instance-os-user "$REMOTE_USER" \
  --ssh-public-key "file://${PUB}" >/dev/null

"${SSH[@]}" "${REMOTE_USER}@${IP}" "chmod +x ${REMOTE_DIR}/deploy/*.sh && ${REMOTE_DIR}/deploy/remote-bootstrap.sh ${REMOTE_DIR}"

echo "==> Done. Open http://${IP}:8010/ui"
