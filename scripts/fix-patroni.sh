#!/usr/bin/env bash
# Simple Patroni troubleshooting script for RHEL 9

set -u

echo "=== Patroni Troubleshooting ==="

# 1. Root check
if [[ $EUID -ne 0 ]]; then
  echo "[FAIL] Must run as root (sudo)." >&2
  exit 1
fi

PATRONI_CFG="/etc/patroni/patroni.yml"

# 2. Check patroni binary
echo
echo "-> Checking if 'patroni' binary is available..."
if command -v patroni >/dev/null 2>&1; then
  PATRONI_BIN="$(command -v patroni)"
  echo "[OK] patroni found at: ${PATRONI_BIN}"
else
  echo "[FAIL] 'patroni' command not found in PATH."
  echo
  echo "This usually means Patroni is not installed on this node."
  echo "Suggested installation options:"
  echo "  - If using system packages:"
  echo "      dnf install -y patroni"
  echo "  - If using wheels from ./rpms/patroni-wheels (offline):"
  echo "      pip3 install --no-index --find-links=./rpms/patroni-wheels patroni"
  echo
  echo "After installing, re-run menu option 3 (Install Required Packages)"
  echo "and menu option 7 (Install & Configure Patroni) in pg_ha_setup.py."
  exit 1
fi

# 3. Check Patroni config
echo
echo "-> Checking Patroni config file: ${PATRONI_CFG}"
if [[ -f "${PATRONI_CFG}" ]]; then
  echo "[OK] Found ${PATRONI_CFG}"
else
  echo "[FAIL] ${PATRONI_CFG} does not exist."
  echo "       Run menu option 7 (Install & Configure Patroni) in pg_ha_setup.py"
  echo "       on this node so the script can generate patroni.yml."
  exit 1
fi

# 4. Check systemd service existence
echo
echo "-> Checking if systemd knows about 'patroni.service'..."
if systemctl list-unit-files | grep -q '^patroni\.service'; then
  echo "[OK] patroni.service unit file is registered."
else
  echo "[WARN] patroni.service unit file not found in systemd."
  echo
  echo "You can create a basic systemd unit like this (adjust ExecStart if needed):"
  cat <<'UNIT'
/etc/systemd/system/patroni.service
----------------------------------
[Unit]
Description=Patroni PostgreSQL HA Cluster Manager
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/patroni -c /etc/patroni/patroni.yml
Restart=on-failure
User=postgres
Group=postgres

[Install]
WantedBy=multi-user.target
UNIT
  echo
  echo "If patroni is installed somewhere else, replace /usr/local/bin/patroni"
  echo "with the actual path shown earlier (${PATRONI_BIN})."
  echo
  echo "After creating the file above, run:"
  echo "  systemctl daemon-reload"
  echo "  systemctl enable patroni"
  echo "  systemctl start patroni"
fi

# 5. Check service status (if systemd can see it)
echo
echo "-> Checking systemctl status patroni..."
if systemctl status patroni >/dev/null 2>&1; then
  systemctl status patroni -l | sed -n '1,20p'
else
  echo "[INFO] systemctl status patroni failed; service may not be created yet."
fi

echo
echo "=== Patroni troubleshooting completed ==="
