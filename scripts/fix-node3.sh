#!/usr/bin/env bash
# fix-node3.sh - Run on NODE3 (172.16.15.38) only.
# Fixes: etcd v2, Patroni unit, starts Patroni.
# Usage: sudo bash scripts/fix-node3.sh
# Before first run: sed -i 's/\r$//' scripts/fix-node3.sh  (if copied from Windows)

set -e

[[ $EUID -eq 0 ]] || { echo "[FAIL] Must run as root (sudo)."; exit 1; }

echo "[INFO] === Node3 fix ==="

# 1. etcd config: v2 API + advertise-client-urls (required by etcd 3.5+)
if ! grep -q 'ETCD_ENABLE_V2' /etc/etcd/etcd.conf 2>/dev/null; then
  echo 'ETCD_ENABLE_V2=true' >> /etc/etcd/etcd.conf
  echo "[INFO] Added ETCD_ENABLE_V2=true to etcd.conf"
else
  sed -i 's/ETCD_ENABLE_V2="true"/ETCD_ENABLE_V2=true/' /etc/etcd/etcd.conf 2>/dev/null || true
fi
# etcd 3.5+ requires ETCD_ADVERTISE_CLIENT_URLS (ETCD_INITIAL_ADVERTISE_CLIENT_URLS is unrecognized)
if ! grep -q 'ETCD_ADVERTISE_CLIENT_URLS' /etc/etcd/etcd.conf 2>/dev/null; then
  echo 'ETCD_ADVERTISE_CLIENT_URLS="http://172.16.15.38:2379"' >> /etc/etcd/etcd.conf
  echo "[INFO] Added ETCD_ADVERTISE_CLIENT_URLS to etcd.conf"
fi
# Remove brackets around IPv4 in etcd URLs (causes Patroni "Invalid IPv6 URL")
sed -i 's/\[\([0-9][0-9.]*\)\]/\1/g' /etc/etcd/etcd.conf 2>/dev/null || true
systemctl restart etcd 2>/dev/null || { echo "[WARN] etcd restart failed"; }
sleep 2

# 2. Fix patroni.service (ExecStart -c, User=intellidb)
if [[ -f /etc/systemd/system/patroni.service ]]; then
  sed -i 's|ExecStart=.*patroni.*patroni\.yml|ExecStart=/usr/local/bin/patroni -c /etc/patroni/patroni.yml|' /etc/systemd/system/patroni.service 2>/dev/null || true
  sed -i 's/^User=postgres$/User=intellidb/' /etc/systemd/system/patroni.service 2>/dev/null || true
  sed -i 's/^Group=postgres$/Group=intellidb/' /etc/systemd/system/patroni.service 2>/dev/null || true
  echo "[INFO] Fixed patroni.service"
fi
# Fix etcd hosts: no brackets around IPv4 (causes Patroni "Invalid IPv6 URL")
[[ -f /etc/patroni/patroni.yml ]] && sed -i 's/\[\([0-9][0-9.]*\)\]/\1/g' /etc/patroni/patroni.yml 2>/dev/null || true
chown intellidb:intellidb /etc/patroni/patroni.yml 2>/dev/null || true
systemctl daemon-reload

# 3. Start Patroni
systemctl start patroni 2>/dev/null || { echo "[FAIL] Patroni failed to start. Check: journalctl -xeu patroni"; exit 1; }
sleep 3
systemctl is-active patroni >/dev/null && echo "[INFO] Patroni is running" || echo "[WARN] Patroni may not be active"

# 4. Cluster status
echo ""
echo "[INFO] Cluster status:"
export PATH="/usr/local/bin:$PATH"
if patronictl -c /etc/patroni/patroni.yml list 2>/dev/null; then
  echo "[INFO] Cluster OK - expect 1 Leader + 2 Replicas"
else
  echo "[WARN] patronictl failed - cluster may still be forming"
fi

echo ""
echo "[INFO] Node3 fix done."
