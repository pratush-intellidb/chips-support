#!/usr/bin/env bash
# fix-node3.sh - Run on NODE3 (172.16.15.38) only.
# Usage: sudo bash scripts/fix-node3.sh

set -e

echo "[INFO] === Node3 fix ==="

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

# 3. Start Patroni
systemctl start patroni
sleep 2
systemctl status patroni --no-pager -l | head -15

# 4. Cluster status
echo ""
echo "[INFO] Cluster status:"
export PATH="/usr/local/bin:$PATH"
patronictl -c /etc/patroni/patroni.yml list 2>/dev/null || echo "[WARN] patronictl failed - run: patronictl -c /etc/patroni/patroni.yml list"

echo ""
echo "[INFO] Node3 fix done."
