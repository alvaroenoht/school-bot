#!/usr/bin/env bash
set -euo pipefail

# ── SchoolBot Production Deploy ──────────────────────────────────────────────
# Run on EC2 after cloning repo and setting up .env
#
# Prerequisites:
#   1. EC2 instance (Ubuntu 22.04+ recommended, t3.small minimum)
#   2. Docker + Docker Compose installed
#   3. Ports 80, 443 open in Security Group
#   4. Elastic IP attached
#   5. Route 53 A records:
#        app.inbilt.co  → <Elastic IP>
#        api.inbilt.co  → <Elastic IP>
#        inbilt.co      → <Elastic IP>
#   6. .env file configured (copy from .env.production template)

echo "── SchoolBot Production Deploy ──"

# Verify .env exists
if [ ! -f .env ]; then
    echo "ERROR: .env file not found. Copy .env.production to .env and fill in values."
    exit 1
fi

# Check for placeholder values
if grep -q "CHANGE_ME" .env; then
    echo "WARNING: .env still has CHANGE_ME placeholders. Fix before proceeding."
    grep "CHANGE_ME" .env
    exit 1
fi

# Build and start
echo "Building and starting services..."
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

echo ""
echo "── Waiting for services ──"
sleep 5

# Health check
echo "Checking services..."
docker compose ps

echo ""
echo "── Deploy complete ──"
echo "  Admin panel: https://app.inbilt.co"
echo "  API:         https://api.inbilt.co"
echo "  WAHA dash:   internal only (no external port)"
echo ""
echo "Next steps:"
echo "  1. Open https://app.inbilt.co — should show login"
echo "  2. Connect WAHA: docker compose exec waha curl http://localhost:3000/api/sessions"
echo "  3. Seed DB: bash scripts/restore.sh"
