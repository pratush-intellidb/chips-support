#!/usr/bin/env bash
# fix-node1.sh - Run on NODE1 (172.16.15.36) only. HAProxy node.
# Fixes: etcd v2, Patroni unit, HAProxy socket dir, starts services.
# Usage: sudo bash scripts/fix-node1.sh
# Before first run: sed -i 's/\r$//' scripts/fix-node1.sh  (if copied from Windows)

set -e

[[ $EUID -eq 0 ]] || { echo "[FAIL] Must run as root (sudo)."; exit 1; }

echo "[INFO] === Node1 fix (HAProxy node) ==="

# 1. Enable etcd v2 API (no quotes - "true" causes 404)
if ! grep -q 'ETCD_ENABLE_V2' /etc/etcd/etcd.conf 2>/dev/null; then
  echo 'ETCD_ENABLE_V2=true' >> /etc/etcd/etcd.conf
  echo "[INFO] Added ETCD_ENABLE_V2=true to etcd.conf"
else
  sed -i 's/ETCD_ENABLE_V2="true"/ETCD_ENABLE_V2=true/' /etc/etcd/etcd.conf 2>/dev/null || true
fi
systemctl restart etcd 2>/dev/null || { echo "[WARN] etcd restart failed"; }
sleep 2

# 2. Fix patroni.service (ExecStart -c, User=intellidb)
if [[ -f /etc/systemd/system/patroni.service ]]; then
  sed -i 's|ExecStart=.*patroni.*patroni\.yml|ExecStart=/usr/local/bin/patroni -c /etc/patroni/patroni.yml|' /etc/systemd/system/patroni.service 2>/dev/null || true
  sed -i 's/^User=postgres$/User=intellidb/' /etc/systemd/system/patroni.service 2>/dev/null || true
  sed -i 's/^Group=postgres$/Group=intellidb/' /etc/systemd/system/patroni.service 2>/dev/null || true
  echo "[INFO] Fixed patroni.service"
fi
chown intellidb:intellidb /etc/patroni/patroni.yml 2>/dev/null || true
systemctl daemon-reload

# 3. HAProxy - create socket dir inside chroot (chroot /var/lib/haproxy)
if [[ -f /etc/haproxy/haproxy.cfg ]]; then
  mkdir -p /var/lib/haproxy/run/haproxy
  chown haproxy:haproxy /var/lib/haproxy/run/haproxy 2>/dev/null || true
  if haproxy -c -f /etc/haproxy/haproxy.cfg 2>/dev/null; then
    systemctl restart haproxy 2>/dev/null && echo "[INFO] HAProxy started" || echo "[WARN] HAProxy failed to start"
  else
    echo "[WARN] HAProxy config invalid - skipping start"
  fi
else
  echo "[WARN] /etc/haproxy/haproxy.cfg not found - skipping HAProxy"
fi

# 4. Start Patroni
systemctl start patroni 2>/dev/null || { echo "[FAIL] Patroni failed to start. Check: journalctl -xeu patroni"; exit 1; }
sleep 3
systemctl is-active patroni >/dev/null && echo "[INFO] Patroni is running" || echo "[WARN] Patroni may not be active"

# 5. Cluster status
echo ""
echo "[INFO] Cluster status:"
export PATH="/usr/local/bin:$PATH"
if patronictl -c /etc/patroni/patroni.yml list 2>/dev/null; then
  echo "[INFO] Cluster OK - expect 1 Leader + 2 Replicas when all nodes are up"
else
  echo "[WARN] patronictl failed - ensure node2 and node3 have run fix-node2.sh and fix-node3.sh"
fi

echo ""
echo "[INFO] Node1 fix done. Run fix-node2.sh on node2, fix-node3.sh on node3."
