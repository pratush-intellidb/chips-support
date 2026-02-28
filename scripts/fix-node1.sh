#!/usr/bin/env bash
# fix-node1.sh - Run on NODE1 (172.16.15.36) only. Fixes etcd v2, Patroni unit, HAProxy.
# Usage: sudo bash scripts/fix-node1.sh

set -e

echo "[INFO] === Node1 fix (HAProxy node) ==="

# 1. Enable etcd v2 API
if ! grep -q 'ETCD_ENABLE_V2' /etc/etcd/etcd.conf 2>/dev/null; then
  echo 'ETCD_ENABLE_V2="true"' >> /etc/etcd/etcd.conf
  echo "[INFO] Added ETCD_ENABLE_V2 to etcd.conf"
  systemctl restart etcd
  sleep 2
fi

# 2. Fix patroni.service (ExecStart -c, User=intellidb for IntelliDB)
sed -i 's|ExecStart=/usr/local/bin/patroni /etc/patroni/patroni.yml|ExecStart=/usr/local/bin/patroni -c /etc/patroni/patroni.yml|' /etc/systemd/system/patroni.service 2>/dev/null || true
sed -i 's|ExecStart=.*patroni.*patroni.yml|ExecStart=/usr/local/bin/patroni -c /etc/patroni/patroni.yml|' /etc/systemd/system/patroni.service 2>/dev/null || true
sed -i 's/^User=postgres$/User=intellidb/' /etc/systemd/system/patroni.service 2>/dev/null || true
sed -i 's/^Group=postgres$/Group=intellidb/' /etc/systemd/system/patroni.service 2>/dev/null || true
chown intellidb:intellidb /etc/patroni/patroni.yml 2>/dev/null || true
systemctl daemon-reload

# 3. HAProxy
haproxy -c -f /etc/haproxy/haproxy.cfg 2>/dev/null && systemctl restart haproxy || echo "[WARN] HAProxy config invalid or service failed"

# 4. Start Patroni
systemctl start patroni
sleep 2
systemctl status patroni --no-pager -l | head -15

# 5. Cluster status
echo ""
echo "[INFO] Cluster status:"
export PATH="/usr/local/bin:$PATH"
patronictl -c /etc/patroni/patroni.yml list 2>/dev/null || echo "[WARN] patronictl failed - run: patronictl -c /etc/patroni/patroni.yml list"

echo ""
echo "[INFO] Node1 fix done."
