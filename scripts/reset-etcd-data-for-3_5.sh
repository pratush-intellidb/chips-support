#!/usr/bin/env bash
# reset-etcd-data-for-3_5.sh
# Wipe etcd data dir so etcd 3.5.x can start after previously running 3.6.x.

set -e

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo bash reset-etcd-data-for-3_5.sh" >&2
  exit 1
fi

ETCD_ENV="/etc/etcd/etcd.conf"

if [[ -f "$ETCD_ENV" ]]; then
  # Try to get ETCD_DATA_DIR from env file
  ETCD_DATA_DIR=$(grep -E '^ETCD_DATA_DIR=' "$ETCD_ENV" | head -1 | cut -d'=' -f2- | tr -d '"')
fi

# Fallback if not set
ETCD_DATA_DIR=${ETCD_DATA_DIR:-/var/lib/etcd}

echo "Using ETCD_DATA_DIR: $ETCD_DATA_DIR"

read -r -p "This will DELETE ALL DATA under $ETCD_DATA_DIR. Continue? [y/N]: " ans
ans=${ans,,}
if [[ "$ans" != "y" ]]; then
  echo "Aborted."
  exit 0
fi

echo "Stopping etcd..."
systemctl stop etcd || true

echo "Deleting contents of $ETCD_DATA_DIR ..."
rm -rf "${ETCD_DATA_DIR:?}/"*

echo "Starting etcd..."
systemctl start etcd

echo "Checking etcd status..."
systemctl status etcd -l | sed -n '1,15p'

echo "Testing /health and /v2/machines ..."
curl -s "http://127.0.0.1:2379/health" || echo "no /health"
echo
curl -s "http://127.0.0.1:2379/v2/machines" || echo "no /v2/machines"

echo
echo "If /v2/machines now returns URLs (not 404), you can restart Patroni:"
echo "  systemctl restart patroni"
