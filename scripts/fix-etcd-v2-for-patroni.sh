#!/usr/bin/env bash
#
# Fix etcd for Patroni: install etcd 3.5.x (with v2 API) so Patroni's etcd DCS works.
# etcd 3.6+ removed the v2 API; Patroni's "etcd" driver requires /v2/machines.
#
# Run on each node as root: sudo bash fix-etcd-v2-for-patroni.sh
# Optionally with a local tarball: sudo bash fix-etcd-v2-for-patroni.sh /path/to/etcd-v3.5.15-linux-amd64.tar.gz
#
set -e

ETCD_VERSION="${ETCD_VERSION:-3.5.15}"
ETCD_TARBALL_NAME="etcd-v${ETCD_VERSION}-linux-amd64.tar.gz"
ETCD_RELEASE_URL="https://github.com/etcd-io/etcd/releases/download/v${ETCD_VERSION}/${ETCD_TARBALL_NAME}"
INSTALL_DIR="/usr/local/bin"
ETCD_CONFIG_DIR="/etc/etcd"
ETCD_DATA_DIR="/var/lib/etcd"

usage() {
  echo "Usage: $0 [path-to-etcd-v3.5.x-linux-amd64.tar.gz]"
  echo "  No argument: look for tarball in ./rpms/ or ., then in /tmp; if not found, download from GitHub."
  echo "  With path:   use that tarball (e.g. ./rpms/etcd-v3.5.15-linux-amd64.tar.gz)."
  exit 0
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
fi

if [[ $EUID -ne 0 ]]; then
  echo "[FAIL] Must run as root (e.g. sudo bash $0)." >&2
  exit 1
fi

# Resolve tarball path
TARBALL=""
if [[ -n "${1:-}" && -f "${1}" ]]; then
  TARBALL="$(realpath "$1")"
  echo "[INFO] Using provided tarball: $TARBALL"
fi

if [[ -z "$TARBALL" ]]; then
  for dir in "rpms" "."; do
    if [[ -d "$dir" ]]; then
      found=$(find "$dir" -maxdepth 1 -name "etcd-v3.5*.tar.gz" 2>/dev/null | head -1)
      if [[ -n "$found" && -f "$found" ]]; then
        TARBALL="$(realpath "$found")"
        echo "[INFO] Using local tarball: $TARBALL"
        break
      fi
    fi
  done
fi

if [[ -z "$TARBALL" ]]; then
  if [[ -f "/tmp/${ETCD_TARBALL_NAME}" ]]; then
    TARBALL="/tmp/${ETCD_TARBALL_NAME}"
    echo "[INFO] Using cached tarball: $TARBALL"
  else
    echo "[INFO] No local tarball found. Downloading ${ETCD_TARBALL_NAME} from GitHub..."
    (cd /tmp && curl -sL -O "$ETCD_RELEASE_URL")
    if [[ ! -f "/tmp/${ETCD_TARBALL_NAME}" ]]; then
      echo "[FAIL] Download failed. Place etcd-v3.5.x-linux-amd64.tar.gz in ./rpms/ or pass path: $0 /path/to/etcd-v3.5.15-linux-amd64.tar.gz" >&2
      exit 1
    fi
    TARBALL="/tmp/${ETCD_TARBALL_NAME}"
  fi
fi

echo "[INFO] Stopping etcd..."
systemctl stop etcd 2>/dev/null || true

echo "[INFO] Backing up existing etcd binaries (if present)..."
for exe in etcd etcdctl; do
  if [[ -f "${INSTALL_DIR}/${exe}" ]]; then
    cp -a "${INSTALL_DIR}/${exe}" "${INSTALL_DIR}/${exe}.bak.$(date +%Y%m%d%H%M%S)" 2>/dev/null || true
  fi
done

echo "[INFO] Extracting and installing etcd from $TARBALL..."
tmpdir=$(mktemp -d)
tar -xzf "$TARBALL" -C "$tmpdir"
# tarball expands to etcd-v3.5.15-linux-amd64/etcd and etcdctl
subdir=$(find "$tmpdir" -maxdepth 1 -type d -name "etcd-v*" | head -1)
if [[ -z "$subdir" || ! -f "${subdir}/etcd" ]]; then
  echo "[FAIL] Tarball layout unexpected (no etcd-v* dir or etcd binary)." >&2
  rm -rf "$tmpdir"
  exit 1
fi
cp -f "${subdir}/etcd" "${subdir}/etcdctl" "$INSTALL_DIR/"
chmod 755 "${INSTALL_DIR}/etcd" "${INSTALL_DIR}/etcdctl"
rm -rf "$tmpdir"

echo "[INFO] Starting etcd..."
systemctl start etcd

echo "[INFO] Waiting for etcd to be ready..."
for i in {1..15}; do
  if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:2379/health" 2>/dev/null | grep -q 200; then
    break
  fi
  sleep 1
done

echo "[INFO] Checking /health..."
curl -s "http://127.0.0.1:2379/health" || true
echo ""

echo "[INFO] Checking /v2/machines (required for Patroni)..."
machines=$(curl -s "http://127.0.0.1:2379/v2/machines" 2>/dev/null || true)
if [[ -n "$machines" && "$machines" != *"404"* ]]; then
  echo "[OK] v2 API is available: $machines"
else
  echo "[WARN] /v2/machines returned: $machines"
  echo "       If you still see 404, etcd may not have started with v2; check journalctl -u etcd -n 30"
fi

echo ""
echo "Next steps:"
echo "  1. On all three nodes, run this script (or install etcd 3.5.x and start etcd)."
echo "  2. Restart Patroni on each node: systemctl restart patroni"
echo "  3. Check cluster: patronictl -c /etc/patroni/patroni.yml list"
echo ""
echo "Done."
