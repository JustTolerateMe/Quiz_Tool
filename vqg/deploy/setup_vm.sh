#!/bin/bash

# VQG Oracle Cloud VM Setup Script
# Run as: sudo bash setup_vm.sh

set -e

echo "--- Updating System ---"
apt-get update
apt-get upgrade -y

echo "--- Installing Dependencies ---"
apt-get install -y python3.11 python3.11-venv redis-server nginx certbot python3-certbot-nginx git build-essential libmagic1

echo "--- Configuring Firewall (Opening 80, 443) ---"
# Oracle Linux uses iptables by default; ensure ports are open
iptables -I INPUT 6 -p tcp --dport 80 -j ACCEPT
iptables -I INPUT 6 -p tcp --dport 443 -j ACCEPT
netfilter-persistent save

echo "--- Starting Redis ---"
systemctl enable redis-server
systemctl start redis-server

echo "--- Setting up Python Virtualenv ---"
# Assuming script is run from inside the cloned repo root
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "--- Preparing Storage Directories ---"
mkdir -p storage/uploads storage/images storage/processed storage/exports
chown -R ubuntu:ubuntu storage

echo "--- Deployment Files Ready ---"
echo "Next steps:"
echo "1. Update .env with production credentials (RPM=30)"
echo "2. Copy vqg_backend.service and vqg_worker.service to /etc/systemd/system/"
echo "3. Copy nginx_vqg.conf to /etc/nginx/sites-available/vqg"
echo "4. ln -s /etc/nginx/sites-available/vqg /etc/nginx/sites-enabled/"
echo "5. systemctl daemon-reload"
echo "6. certbot --nginx -d YOUR_DOMAIN"
