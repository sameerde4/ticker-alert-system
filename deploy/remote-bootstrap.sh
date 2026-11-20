#!/usr/bin/env bash
# Run on the EC2 host after code is synced to /opt/market-radar
set -euo pipefail

ROOT="${1:-/opt/market-radar}"
cd "$ROOT"

echo "==> Growing root filesystem if volume was expanded"
sudo growpart /dev/nvme0n1 1 2>/dev/null || sudo growpart /dev/xvda 1 2>/dev/null || true
sudo xfs_growfs / 2>/dev/null || sudo resize2fs "$(findmnt -n -o SOURCE /)" 2>/dev/null || true
df -h /

echo "==> Installing Docker (Amazon Linux 2023)"
if ! command -v docker >/dev/null 2>&1; then
  sudo dnf install -y docker
  sudo systemctl enable --now docker
  sudo usermod -aG docker ec2-user || true
fi
# Compose plugin
if ! docker compose version >/dev/null 2>&1; then
  sudo mkdir -p /usr/local/lib/docker/cli-plugins
  sudo curl -fsSL "https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-linux-x86_64" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi
docker --version
docker compose version

echo "==> Fetching Alpaca credentials"
chmod +x deploy/fetch-alpaca-env.sh deploy/migrate.sh
./deploy/fetch-alpaca-env.sh "$ROOT/deploy/alpaca.env"

echo "==> Building and starting stack"
cd "$ROOT"
sudo docker compose -f deploy/docker-compose.yml up -d --build

echo "==> Status"
sudo docker compose -f deploy/docker-compose.yml ps
echo "UI should be at http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4):8010/ui"
