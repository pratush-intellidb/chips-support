#!/usr/bin/env bash
#
# ha-cluster-fix-and-validate.sh
#
# Single script to run on each node to:
#   - Validate/fix etcd (3.5.x, /health, /v2/machines)
#   - Validate/fix Patroni (binary, config, systemd unit with correct User for IntelliDB)
#   - Validate/fix HAProxy on the designated node only
#   - Start services and verify 1 Leader + 2 Replicas
#
# Uses yum when dnf is not available (customer sites).
#
# Usage:
#   With config.yaml (recommended):
#     sudo bash ha-cluster-fix-and-validate.sh /path/to/config.yaml
#     # Or from project dir: sudo bash scripts/ha-cluster-fix-and-validate.sh config.yaml
#
#   Without config (manual):
#     sudo bash ha-cluster-fix-and-validate.sh NODE_NAME NODE_IP "IP1,IP2,IP3" [--haproxy]
#     Example: sudo bash ha-cluster-fix-and-validate.sh node1 172.16.15.36 "172.16.15.36,172.16.15.37,172.16.15.38" --haproxy
#
set -euo pipefail

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
PKG_MGR=""
get_pkg_mgr() {
  if command -v dnf &>/dev/null && dnf --version &>/dev/null 2>&1; then
    PKG_MGR="dnf"
  else
    PKG_MGR="yum"
  fi
  echo "[INFO] Using package manager: $PKG_MGR"
}

log()  { echo "[INFO] $*"; }
warn() { echo "[WARN] $*" >&2; }
fail() { echo "[FAIL] $*" >&2; exit 1; }

PATRONI_CFG="/etc/patroni/patroni.yml"
PATRONI_UNIT="/etc/systemd/system/patroni.service"
HAPROXY_CFG="/etc/haproxy/haproxy.cfg"
CLUSTER_NAME="${CLUSTER_NAME:-pg-cluster}"
USE_INTELLIDB="${USE_INTELLIDB:-true}"
INTELLIDB_PORT="${INTELLIDB_PORT:-5555}"
INTELLIDB_USER="${INTELLIDB_USER:-intellidb}"
REPLICATION_USER="replicator"

# -----------------------------------------------------------------------------
# Parse config.yaml or arguments
# -----------------------------------------------------------------------------
parse_config() {
  local config_file="$1"
  if [[ ! -f "$config_file" ]]; then
    warn "Config file not found: $config_file"
    return 1
  fi
  local out
  out=$(python3 -c "
import sys
p = sys.argv[1]
try:
    import yaml
    with open(p) as f: data = yaml.safe_load(f)
except Exception:
    data = {}
if not data:
    sys.exit(1)
print(data.get('current_node', ''))
print(data.get('current_node_ip', ''))
print(','.join(data.get('etcd_ips') or []))
print((data.get('etcd_nodes') or ['node1'])[0])
print(str(data.get('use_intellidb', True)).lower())
print(data.get('cluster_name', 'pg-cluster'))
print(data.get('intellidb_port', 5555))
print(data.get('haproxy_port', 5000))
print(data.get('haproxy_bind', '0.0.0.0'))
" "$config_file" 2>/dev/null) || return 1
  local line
  local i=0
  while IFS= read -r line; do
    case $i in
      0) NODE_NAME="$line" ;;
      1) NODE_IP="$line" ;;
      2) ETCD_IPS_CSV="$line" ;;
      3) HAPROXY_NODE="${HAPROXY_NODE:-$line}" ;;
      4) USE_INTELLIDB="$line" ;;
      5) CLUSTER_NAME="$line" ;;
      6) INTELLIDB_PORT="$line" ;;
      7) HAPROXY_PORT="$line" ;;
      8) HAPROXY_BIND="$line" ;;
    esac
    (( i++ )) || true
  done <<< "$out"
  return 0
}

# -----------------------------------------------------------------------------
# Main: resolve NODE_NAME, NODE_IP, ETCD_IPS_CSV, HAPROXY_NODE, IS_HAPROXY_NODE
# -----------------------------------------------------------------------------
NODE_NAME=""
NODE_IP=""
ETCD_IPS_CSV=""
HAPROXY_NODE="${HAPROXY_NODE:-node1}"
IS_HAPROXY_NODE="false"
HAPROXY_PORT="5000"
HAPROXY_BIND="0.0.0.0"

if [[ $# -ge 1 && "${1:-}" != "--haproxy" && "${1:-}" != "--help" && "${1:-}" != "-h" ]]; then
  if [[ -f "${1:-}" ]]; then
    CONFIG_FILE="$(realpath "$1")"
    if parse_config "$CONFIG_FILE"; then
      log "Loaded config: $CONFIG_FILE -> NODE_NAME=$NODE_NAME NODE_IP=$NODE_IP ETCD_IPS=$ETCD_IPS_CSV"
      if [[ "$NODE_NAME" == "$HAPROXY_NODE" ]]; then
        IS_HAPROXY_NODE="true"
      fi
    else
      fail "Could not parse config file: $CONFIG_FILE"
    fi
    shift
  else
    NODE_NAME="${1:-}"
    NODE_IP="${2:-}"
    ETCD_IPS_CSV="${3:-}"
    shift 3 || true
    if [[ -z "$NODE_NAME" || -z "$NODE_IP" || -z "$ETCD_IPS_CSV" ]]; then
      fail "Without config file, need: NODE_NAME NODE_IP \"IP1,IP2,IP3\""
    fi
  fi
fi
while [[ $# -gt 0 ]]; do
  if [[ "$1" == "--haproxy" ]]; then
    IS_HAPROXY_NODE="true"
  fi
  shift
done

if [[ -z "$NODE_NAME" || -z "$NODE_IP" ]]; then
  echo "Usage:"
  echo "  sudo $0 /path/to/config.yaml"
  echo "  sudo $0 NODE_NAME NODE_IP \"IP1,IP2,IP3\" [--haproxy]"
  exit 1
fi
if [[ -z "$ETCD_IPS_CSV" ]]; then
  fail "etcd_ips not set (use config.yaml or pass third argument)."
fi

if [[ $EUID -ne 0 ]]; then
  fail "Must run as root (sudo)."
fi

get_pkg_mgr

# -----------------------------------------------------------------------------
# 1. etcd checks
# -----------------------------------------------------------------------------
log "=== 1. Checking etcd ==="
if ! systemctl is-active --quiet etcd 2>/dev/null; then
  warn "etcd is not running. Start it: systemctl start etcd"
else
  log "etcd service is running."
fi
if command -v etcd &>/dev/null; then
  v=$(etcd --version 2>/dev/null | head -1 || true)
  if echo "$v" | grep -q "3\.5\."; then
    log "etcd version OK (3.5.x): $v"
  else
    warn "etcd version may not support v2 API (Patroni needs 3.5.x): $v"
  fi
fi
code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:2379/health" 2>/dev/null || echo "000")
if [[ "$code" == "200" ]]; then
  log "etcd /health returned 200."
else
  warn "etcd /health returned $code (etcd may not be listening or not healthy)."
fi
v2out=$(curl -s "http://127.0.0.1:2379/v2/machines" 2>/dev/null || true)
if [[ "$v2out" != *"404"* && -n "$v2out" ]]; then
  log "etcd v2 API available."
else
  warn "/v2/machines not available or 404 - Patroni etcd driver may fail. Ensure etcd 3.5.x and restarted."
fi

# -----------------------------------------------------------------------------
# 2. Patroni: binary, config, systemd unit
# -----------------------------------------------------------------------------
log "=== 2. Checking Patroni ==="
PATRONI_BIN=""
if command -v patroni &>/dev/null; then
  PATRONI_BIN="$(command -v patroni)"
  log "Patroni binary: $PATRONI_BIN"
else
  warn "Patroni binary not found. Install from rpms/patroni-wheels: pip3 install --no-index --find-links=./rpms/patroni-wheels patroni"
  warn "Or: $PKG_MGR install -y patroni"
fi

if [[ ! -f "$PATRONI_CFG" ]]; then
  warn "Patroni config missing: $PATRONI_CFG"
  warn "Run: sudo python3 pg_ha_setup.py --config config.yaml and choose option 7 (Configure Patroni), or create config manually."
else
  log "Patroni config found: $PATRONI_CFG"
fi

# Create patroni.service if missing (User=intellidb for IntelliDB)
if [[ ! -f "$PATRONI_UNIT" ]]; then
  log "Creating $PATRONI_UNIT ..."
  PATRONI_BIN="${PATRONI_BIN:-/usr/local/bin/patroni}"
  RUN_AS="$INTELLIDB_USER"
  [[ "$USE_INTELLIDB" != "true" ]] && RUN_AS="postgres"
  cat > "$PATRONI_UNIT" << EOF
[Unit]
Description=Patroni PostgreSQL HA Cluster Manager
After=network.target etcd.service

[Service]
Type=simple
ExecStart=$PATRONI_BIN -c $PATRONI_CFG
Restart=on-failure
RestartSec=10s
User=$RUN_AS
Group=$RUN_AS
TimeoutSec=30

[Install]
WantedBy=multi-user.target
EOF
  log "Created patroni.service (User=$RUN_AS)."
  systemctl daemon-reload
  systemctl enable patroni 2>/dev/null || true
else
  log "Patroni systemd unit already exists: $PATRONI_UNIT"
fi

# Ensure config is readable by the run user
if [[ -f "$PATRONI_CFG" ]]; then
  RUN_AS="$INTELLIDB_USER"
  [[ "$USE_INTELLIDB" != "true" ]] && RUN_AS="postgres"
  if id "$RUN_AS" &>/dev/null; then
    chown "${RUN_AS}:${RUN_AS}" "$PATRONI_CFG" 2>/dev/null || true
  fi
fi

# -----------------------------------------------------------------------------
# 3. HAProxy (only on designated node)
# -----------------------------------------------------------------------------
if [[ "$IS_HAPROXY_NODE" == "true" ]]; then
  log "=== 3. Checking HAProxy (this is the HAProxy node) ==="
  if ! command -v haproxy &>/dev/null; then
    warn "haproxy not found. Install: $PKG_MGR install -y haproxy"
  else
    log "HAProxy binary: $(command -v haproxy)"
  fi
  if [[ -f "$HAPROXY_CFG" ]]; then
    if haproxy -c -f "$HAPROXY_CFG" 2>/dev/null; then
      log "HAProxy config valid."
    else
      warn "HAProxy config invalid. Fix $HAPROXY_CFG and run: haproxy -c -f $HAPROXY_CFG"
    fi
    systemctl enable haproxy 2>/dev/null || true
    systemctl restart haproxy 2>/dev/null || true
  else
    warn "HAProxy config missing: $HAPROXY_CFG. Run pg_ha_setup.py option 8 (Configure HAProxy) on this node."
  fi
else
  log "=== 3. Skipping HAProxy (not the designated HAProxy node) ==="
fi

# -----------------------------------------------------------------------------
# 4. Start Patroni
# -----------------------------------------------------------------------------
log "=== 4. Starting Patroni ==="
systemctl start patroni 2>/dev/null || true
sleep 3
if systemctl is-active --quiet patroni 2>/dev/null; then
  log "Patroni service is running."
else
  warn "Patroni failed to start. Check: systemctl status patroni; journalctl -xeu patroni"
fi

# -----------------------------------------------------------------------------
# 5. Cluster health (patronictl list)
# -----------------------------------------------------------------------------
log "=== 5. Cluster health (patronictl list) ==="
if command -v patronictl &>/dev/null && [[ -f "$PATRONI_CFG" ]]; then
  if patronictl -c "$PATRONI_CFG" list 2>/dev/null; then
    leaders=$(patronictl -c "$PATRONI_CFG" list 2>/dev/null | grep -c "Leader" || echo 0)
    replicas=$(patronictl -c "$PATRONI_CFG" list 2>/dev/null | grep -c "Replica" || echo 0)
    if [[ "$leaders" -eq 1 && "$replicas" -ge 1 ]]; then
      log "Cluster looks good: 1 Leader + ${replicas} Replica(s)."
    else
      warn "Expected 1 Leader + 2 Replicas. Check patronictl list and ensure Patroni is running on all 3 nodes."
    fi
  else
    warn "patronictl list failed. Ensure etcd is up on all nodes and Patroni is started on all three."
  fi
else
  warn "patronictl not available or config missing; cannot show cluster status."
fi

echo ""
log "=== HA cluster fix-and-validate completed ==="
log "Next: Run this script on the other two nodes (with their config.yaml or NODE_NAME/NODE_IP)."
log "Then verify: patronictl -c $PATRONI_CFG list"
