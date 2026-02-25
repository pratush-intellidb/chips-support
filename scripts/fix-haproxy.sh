#!/usr/bin/env bash
# Simple HAProxy troubleshooting script for RHEL 9

set -u

echo "=== HAProxy Troubleshooting ==="

# 1. Check root
if [[ $EUID -ne 0 ]]; then
  echo "[FAIL] Must run as root (sudo)." >&2
  exit 1
fi

# 2. Check if haproxy binary exists in PATH
echo
echo "-> Checking if 'haproxy' binary is available..."
if command -v haproxy >/dev/null 2>&1; then
  echo "[OK] haproxy found at: $(command -v haproxy)"
else
  echo "[FAIL] 'haproxy' command not found in PATH."
  echo "       Likely the haproxy package is not installed on this node."
  echo
  echo "Suggested fix:"
  echo "  dnf install -y haproxy"
  echo
  echo "After installing, re-run menu option 3 (Install Required Packages) if needed,"
  echo "then menu option 8 (Configure HAProxy) in pg_ha_setup.py."
  exit 1
fi

# 3. Check config file presence
HAPROXY_CFG="/etc/haproxy/haproxy.cfg"
echo
echo "-> Checking HAProxy config file: ${HAPROXY_CFG}"
if [[ -f "${HAPROXY_CFG}" ]]; then
  echo "[OK] Found ${HAPROXY_CFG}"
else
  echo "[WARN] ${HAPROXY_CFG} does not exist yet."
  echo "       Run menu option 8 (Configure HAProxy) in pg_ha_setup.py to generate it."
  # We can still continue to check the service, but validation will fail without config.
fi

# 4. Validate HAProxy configuration (if file exists)
if [[ -f "${HAPROXY_CFG}" ]]; then
  echo
  echo "-> Validating HAProxy configuration..."
  if haproxy -c -f "${HAPROXY_CFG}"; then
    echo "[OK] haproxy -c validation succeeded."
  else
    echo "[FAIL] haproxy -c validation failed. See errors above."
    echo "       Fix the issues in ${HAPROXY_CFG} and retry."
  fi
fi

# 5. Check systemd service status
echo
echo "-> Checking systemd service status for haproxy..."
if systemctl status haproxy >/dev/null 2>&1; then
  systemctl status haproxy -l | sed -n '1,15p'
else
  echo "[WARN] systemd does not know about 'haproxy' service yet."
  echo "       You may need to enable/start it:"
  echo "         systemctl enable haproxy"
  echo "         systemctl start haproxy"
fi

# 6. Check listening ports
echo
echo "-> Checking listening ports for haproxy (default 5000)..."
if command -v ss >/dev/null 2>&1; then
  ss -tulnp | grep -i haproxy || echo "[INFO] No haproxy listeners found in ss output."
else
  echo "[WARN] 'ss' command not available to inspect ports."
fi

echo
echo "=== HAProxy troubleshooting completed ==="
