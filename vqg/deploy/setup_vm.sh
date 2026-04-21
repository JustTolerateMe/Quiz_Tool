#!/bin/bash
# VQG Hetzner Setup Script — Ubuntu 24.04 LTS
# Run as root: bash setup_vm.sh

set -e

REPO_URL="https://github.com/JustTolerateMe/Quiz_Tool.git"
APP_DIR="/home/ubuntu/vqg"
DEPLOY_DIR="$APP_DIR/vqg"

# ─────────────────────────────────────────────
# 0. Collect secrets upfront
# ─────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════"
echo "  VQG — Hetzner Setup"
echo "════════════════════════════════════════"
echo ""
read -p "Enter your Gemini API key: " GEMINI_API_KEY
echo ""

# ─────────────────────────────────────────────
# 1. System packages
# ─────────────────────────────────────────────
echo "--- Updating system ---"
apt-get update -qq
apt-get upgrade -y -qq

echo "--- Installing system dependencies ---"
apt-get install -y -qq \
    python3.11 python3.11-venv python3-pip \
    redis-server nginx git \
    build-essential curl ufw

# Node.js 20 LTS
echo "--- Installing Node.js 20 ---"
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y -qq nodejs

# ─────────────────────────────────────────────
# 2. Create ubuntu user (if not exists)
# ─────────────────────────────────────────────
if ! id ubuntu &>/dev/null; then
    echo "--- Creating ubuntu user ---"
    useradd -m -s /bin/bash ubuntu
fi

# ─────────────────────────────────────────────
# 3. Clone repo
# ─────────────────────────────────────────────
echo "--- Cloning repo ---"
if [ -d "$APP_DIR" ]; then
    echo "Directory $APP_DIR exists — pulling latest"
    cd "$APP_DIR" && git pull
else
    git clone "$REPO_URL" "$APP_DIR"
fi
chown -R ubuntu:ubuntu "$APP_DIR"

# ─────────────────────────────────────────────
# 4. Python virtualenv + dependencies
# ─────────────────────────────────────────────
echo "--- Setting up Python venv ---"
cd "$DEPLOY_DIR"
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q

# ─────────────────────────────────────────────
# 5. Detect server IP and write .env
# ─────────────────────────────────────────────
echo "--- Detecting server IP ---"
SERVER_IP=$(curl -s https://ipinfo.io/ip)
echo "Server IP: $SERVER_IP"

cat > "$DEPLOY_DIR/.env" <<EOF
GEMINI_API_KEY=$GEMINI_API_KEY
GEMINI_FLASH_MODEL=gemini-3-flash-preview
NANO_BANANA_MODEL=gemini-3.1-flash-image-preview
REDIS_URL=redis://localhost:6379/0
STORAGE_PATH=$DEPLOY_DIR/storage
DATABASE_URL=sqlite:///$DEPLOY_DIR/vqg.db
MAX_IMAGES_PER_PDF=300
SSIM_PASS_THRESHOLD=0.82
GEMINI_RPM_PER_WORKER=55
EOF

chown ubuntu:ubuntu "$DEPLOY_DIR/.env"
chmod 600 "$DEPLOY_DIR/.env"

# ─────────────────────────────────────────────
# 6. Build Next.js frontend
# ─────────────────────────────────────────────
echo "--- Building Next.js frontend ---"
cd "$DEPLOY_DIR/frontend"
cat > .env.local <<EOF
NEXT_PUBLIC_API_URL=http://$SERVER_IP
EOF
npm install --silent
npm run build

# ─────────────────────────────────────────────
# 7. Storage directories
# ─────────────────────────────────────────────
echo "--- Creating storage directories ---"
mkdir -p "$DEPLOY_DIR/storage/uploads" \
         "$DEPLOY_DIR/storage/images" \
         "$DEPLOY_DIR/storage/processed" \
         "$DEPLOY_DIR/storage/exports"
chown -R ubuntu:ubuntu "$DEPLOY_DIR/storage"

# ─────────────────────────────────────────────
# 8. Redis — use system Redis (default port 6379)
# ─────────────────────────────────────────────
echo "--- Enabling Redis ---"
systemctl enable redis-server
systemctl start redis-server

# ─────────────────────────────────────────────
# 9. Systemd services
# ─────────────────────────────────────────────
echo "--- Installing systemd services ---"
cp "$DEPLOY_DIR/deploy/vqg_backend.service"  /etc/systemd/system/
cp "$DEPLOY_DIR/deploy/vqg_worker.service"   /etc/systemd/system/
cp "$DEPLOY_DIR/deploy/vqg_frontend.service" /etc/systemd/system/

systemctl daemon-reload
systemctl enable vqg_backend vqg_worker vqg_frontend
systemctl start  vqg_backend vqg_worker vqg_frontend

# ─────────────────────────────────────────────
# 10. Nginx
# ─────────────────────────────────────────────
echo "--- Configuring Nginx ---"
cp "$DEPLOY_DIR/deploy/nginx_vqg.conf" /etc/nginx/sites-available/vqg
ln -sf /etc/nginx/sites-available/vqg /etc/nginx/sites-enabled/vqg
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable nginx
systemctl restart nginx

# ─────────────────────────────────────────────
# 11. Firewall
# ─────────────────────────────────────────────
echo "--- Configuring firewall ---"
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

# ─────────────────────────────────────────────
# Done
# ─────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════"
echo "  Setup complete!"
echo "  VQG is running at: http://$SERVER_IP"
echo "════════════════════════════════════════"
echo ""
echo "Useful commands:"
echo "  systemctl status vqg_backend"
echo "  systemctl status vqg_worker"
echo "  systemctl status vqg_frontend"
echo "  journalctl -u vqg_worker -f    # live worker logs"
echo ""
