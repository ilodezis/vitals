#!/bin/bash
set -e

echo "=== 1. System Update and Upgrade ==="
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get upgrade -y

echo "=== 2. Installing Prerequisites ==="
apt-get install -y ca-certificates curl gnupg ufw

echo "=== 3. Configuring Sysctl Swappiness & Keepalives ==="
# Swappiness to 10 for performance
if ! grep -q "vm.swappiness" /etc/sysctl.conf; then
    echo "vm.swappiness=10" >> /etc/sysctl.conf
fi
# Keepalive settings
if ! grep -q "net.ipv4.tcp_keepalive_time" /etc/sysctl.conf; then
    echo "net.ipv4.tcp_keepalive_time=60" >> /etc/sysctl.conf
    echo "net.ipv4.tcp_keepalive_intvl=10" >> /etc/sysctl.conf
    echo "net.ipv4.tcp_keepalive_probes=6" >> /etc/sysctl.conf
fi
sysctl -p

echo "=== 4. Installing Docker ==="
# Remove any legacy docker
apt-get remove -y docker docker-engine docker.io containerd runc || true

# Add Docker's official GPG key:
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

# Add the repository to Apt sources:
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Verify docker works
docker --version
docker compose version

echo "=== 5. Configuring UFW Firewall ==="
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "=== 6. Disabling Password Authentication ==="
# Modern sshd includes everything in sshd_config.d/
# We write to a 99-disable-password.conf to override previous files
cat << 'EOF' > /etc/ssh/sshd_config.d/99-disable-password.conf
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
PubkeyAuthentication yes
EOF

# Restart sshd
systemctl restart sshd

echo "=== Setup Completed Successfully! ==="
