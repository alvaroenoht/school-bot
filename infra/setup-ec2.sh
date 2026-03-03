#!/bin/bash
# ── One-time EC2 setup script ─────────────────────────────────────────────────
# Run this once after launching a fresh Ubuntu 22.04 EC2 t3.micro instance.
# Installs Docker, pulls the repo, and starts the stack.

set -e

echo "▶ Installing Docker..."
sudo apt-get update -y
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update -y
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

sudo usermod -aG docker $USER
echo "✅ Docker installed"

echo "▶ Cloning repo..."
git clone https://github.com/YOUR_USERNAME/schoolbot.git ~/schoolbot
cd ~/schoolbot

echo "▶ Creating .env file..."
cp .env.example .env
echo ""
echo "⚠️  Edit ~/schoolbot/.env with your real values before continuing:"
echo "    nano ~/schoolbot/.env"
echo ""
echo "Then run:"
echo "    cd ~/schoolbot && docker compose up -d"
echo ""
echo "▶ Setup complete. Configure .env and start the stack."
