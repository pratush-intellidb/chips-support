#!/bin/bash
# IntelliDB PostgreSQL HA Setup on RHEL 9
# Run this script INSIDE a RHEL 9 / Rocky Linux 9 container with /mnt/host
# bound to your project directory.
#
# On Rocky/RHEL 9, etcd and patroni are NOT in EPEL. This script:
#   1) Downloads RPMs that exist: postgresql17-*, haproxy, firewalld, python3-*
#   2) Downloads etcd from GitHub releases (tarball)
#   3) Downloads Patroni and deps via pip (wheels)
set -e

echo "=== Enabling EPEL and CRB ==="
dnf -y install epel-release dnf-plugins-core
dnf config-manager --set-enabled crb 2>/dev/null || true

echo "=== Enabling PostgreSQL 17 (PGDG) repo ==="
dnf -y install https://download.postgresql.org/pub/repos/yum/reporpms/EL-9-x86_64/pgdg-redhat-repo-latest.noarch.rpm
dnf -qy module disable postgresql

echo "=== Creating output directory /mnt/host/rpms ==="
mkdir -p /mnt/host/rpms
cd /mnt/host/rpms

echo "=== Downloading RPMs (postgresql17, haproxy, firewalld, python3-*) ==="
dnf -y download \
  postgresql17-server postgresql17-contrib \
  haproxy firewalld \
  python3-psycopg2 python3-pyyaml

echo "=== Downloading etcd 3.5.x (not in EPEL for EL9; 3.5 has v2 API required by Patroni) ==="
curl -sL -o etcd-v3.5.15-linux-amd64.tar.gz \
  https://github.com/etcd-io/etcd/releases/download/v3.5.15/etcd-v3.5.15-linux-amd64.tar.gz

echo "=== Downloading Patroni and deps (wheels; not in EPEL for EL9) ==="
dnf -y install python3-pip 2>/dev/null || true
pip3 download patroni -d /mnt/host/rpms/patroni-wheels

echo "=== Done. Output in /mnt/host/rpms (host: ./rpms) ==="
ls -la
ls -la patroni-wheels 2>/dev/null || true
