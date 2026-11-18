#!/usr/bin/env bash
set -euo pipefail

SRC_FILE="/etc/apt/sources.list.d/ubuntu.sources"
if [[ -f "$SRC_FILE" ]]; then
  sudo cp "$SRC_FILE" "${SRC_FILE}.bak"
  sudo sed -i 's|ap-osaka-1-ad-1.clouds.archive.ubuntu.com|archive.ubuntu.com|g' "$SRC_FILE"
fi
if [[ -f /etc/apt/sources.list ]]; then
  sudo sed -i 's|ap-osaka-1-ad-1.clouds.archive.ubuntu.com|archive.ubuntu.com|g' /etc/apt/sources.list
fi

sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  iptables-persistent python3 python3-venv python3-pip git

# Open app port in iptables (best-effort)
sudo iptables -C INPUT -p tcp --dport 8000 -j ACCEPT 2>/dev/null \
  || sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8000 -j ACCEPT
sudo netfilter-persistent save || true

APP_DIR="/home/ubuntu/AdOpsAssistant"
if [[ ! -d "$APP_DIR/.git" ]]; then
  git clone https://github.com/gitit-emkoo/AdOpsAssistant.git "$APP_DIR"
else
  cd "$APP_DIR"
  git pull --ff-only || true
fi

cd "$APP_DIR"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "BOOTSTRAP_OK"
