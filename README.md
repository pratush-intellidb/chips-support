# IntelliDB PostgreSQL HA Setup on RHEL 9

Production-grade, menu-driven Python 3 console application that automates PostgreSQL 17 High Availability setup on RHEL 9 using **Patroni**, **etcd**, **HAProxy**, **firewalld**, **SELinux**, and **systemd**.

**Version:** 1.0.0

---

## Table of Contents

- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [Network Ports](#network-ports)
- [Configuration](#configuration)
- [Command-Line Options](#command-line-options)
- [Menu Reference](#menu-reference)
- [Logging and Troubleshooting](#logging-and-troubleshooting)
- [Security](#security)
- [Support](#support)

---

## Requirements

- **OS:** RHEL 9 (or compatible: Rocky Linux 9, AlmaLinux 9, CentOS Stream 9)
- **Privileges:** Root (sudo) for installation and configuration
- **Python:** 3.6 or later (stdlib only; PyYAML optional for config file)
- **Network:** Connectivity between 3 etcd nodes on ports 2379, 2380
- **Prerequisites:** firewalld, systemd (default on RHEL 9)
- **Offline/air‑gapped:** All required RPMs must be available from local/internal yum repos
  (the script never downloads from the public internet).

---

## Quick Start

```bash
# Optional: install PyYAML for YAML config file support
pip3 install pyyaml
# or: sudo dnf install python3-pyyaml

# Run as root
sudo python3 pg_ha_setup.py
```

Recommended first steps from the menu:

1. **Validate System Requirements** – confirm OS, root, firewalld, ports.
2. **Show Required Ports & Open Firewall Ports** – review ports and open them.
3. Proceed with **Install Required Packages** and subsequent steps.

---

## Network Ports

| Port | Service            | Purpose                          | Exposure        |
|------|--------------------|----------------------------------|-----------------|
| 5432 | PostgreSQL         | Client connections               | Internal only   |
| 8008 | Patroni REST API   | Health checks, leader detection  | Cluster only    |
| 2379 | etcd client        | DCS communication               | Cluster only    |
| 2380 | etcd peer          | etcd replication                 | Cluster only    |
| 5000 | HAProxy            | Frontend (configurable)          | App tier        |
| 7000 | Read replica       | Optional (configurable)         | Internal/optional |

Use menu option **2** to see full port documentation and open/verify firewall ports.

---

## Configuration

Use `config.example.yaml` as a template. Copy and customize for your environment:

```bash
cp config.example.yaml config.yaml
# Edit config.yaml: set etcd_ips, current_node, current_node_ip, passwords
sudo python3 pg_ha_setup.py --config config.yaml
```

- **Per-node:** Set `current_node` and `current_node_ip` for each host (e.g. node1/node2/node3).
- **Passwords:** Leave `replication_password` and `postgres_password` empty to be prompted (masked) at runtime.
- **Do not commit** `config.yaml` with real passwords to version control.

---

## Downloading RPMs for offline install (Docker)

On RHEL 9 / Rocky Linux 9, **etcd** and **patroni** are in **EPEL**, not the base repos. Enable EPEL first, then download.

**Option A – Use the provided script (recommended)**

From your project directory (e.g. `C:\Feb-2026\HA-Setup-PgSQL-RHEL9`):

**PowerShell (Windows):**
```powershell
cd C:\Feb-2026\HA-Setup-PgSQL-RHEL9
docker pull rockylinux:9
docker run --rm -it -v "${PWD}:/mnt/host" rockylinux:9 bash -c "dnf -y install epel-release; dnf -y update; dnf -y install dnf-plugins-core; dnf -y install https://download.postgresql.org/pub/repos/yum/reporpms/EL-9-x86_64/pgdg-redhat-repo-latest.noarch.rpm; dnf -qy module disable postgresql; mkdir -p /mnt/host/rpms && cd /mnt/host/rpms && dnf -y download postgresql17-server postgresql17-contrib patroni etcd haproxy firewalld python3-psycopg2 python3-pyyaml; ls -la"
```

**Bash (Linux/macOS):**
```bash
docker pull rockylinux:9
docker run --rm -it -v "$(pwd):/mnt/host" rockylinux:9 bash -c "
  dnf -y install epel-release
  dnf -y update
  dnf -y install dnf-plugins-core
  dnf -y install https://download.postgresql.org/pub/repos/yum/reporpms/EL-9-x86_64/pgdg-redhat-repo-latest.noarch.rpm
  dnf -qy module disable postgresql
  mkdir -p /mnt/host/rpms && cd /mnt/host/rpms
  dnf -y download postgresql17-server postgresql17-contrib patroni etcd haproxy firewalld python3-psycopg2 python3-pyyaml
  ls -la
"
```

RPMs will appear in `.\rpms` (or `./rpms` on Linux).

**Option B – Run script interactively**

```powershell
docker run --rm -it -v "C:\Feb-2026\HA-Setup-PgSQL-RHEL9:/mnt/host" rockylinux:9 /bin/bash
# Inside container:
bash /mnt/host/scripts/download-rpms-in-docker.sh
exit
```

**Fix for "No package etcd available":** install **EPEL** before the download step (`dnf -y install epel-release`). The commands above do that.

---

## Command-Line Options

| Option | Description |
|--------|-------------|
| `--config`, `-c` | Path to YAML configuration file |
| `--dry-run` | Simulate actions without making changes |
| `--non-interactive` | With `--config`: run validation and port/firewall menu only |
| `--version`, `-v` | Print version and exit |

Examples:

```bash
sudo python3 pg_ha_setup.py --config /etc/pg_ha_setup/config.yaml
sudo python3 pg_ha_setup.py --dry-run
sudo python3 pg_ha_setup.py --version
```

---

## Menu Reference

| # | Option |
|---|--------|
| 1 | Validate System Requirements |
| 2 | Show Required Ports & Open Firewall Ports |
| 3 | Install Required Packages |
| 4 | Configure etcd Cluster |
| 5 | Install PostgreSQL 17 |
| 6 | Configure PostgreSQL Replication |
| 7 | Install & Configure Patroni |
| 8 | Configure HAProxy |
| 9 | Configure SELinux Policies |
| 10 | Initialize Cluster |
| 11 | Check Cluster Health |
| 12 | Simulate Failover |
| 13 | Backup Using pg_basebackup |
| 14 | Full Automated Setup |
| 15 | Uninstall HA Stack |
| 16 | Security Hardening (Info) |
| 17 | Enable TLS (Self-Signed Certs) |
| 18 | Exit |

---

## Logging and Troubleshooting

- **Log file:** `/var/log/pg_ha_setup.log` (created when run as root).
- **HAProxy:** Config is validated with `haproxy -c -f ...` before reload; errors are shown and reload is skipped on failure.
- **SELinux:** If `restorecon` is not found (e.g. minimal install), SELinux step is skipped with a warning. For AVC denials: `ausearch -m avc -ts recent`.
- **Patroni/etcd:** If packages are not in default repos, install from your vendor’s repository or follow Patroni/etcd upstream docs for RHEL 9.
- **Offline environments:** Pre-stage or mirror all required RPMs (`postgresql17-*`, `patroni`,
  `etcd`, `haproxy`, `firewalld`, `python3-psycopg2`, `python3-pyyaml`) into your internal
  repositories. The `Install Required Packages` step only uses `dnf` against existing repos.

---

## Security

- Restrict **pg_hba.conf** to application CIDR in production (avoid 0.0.0.0/0).
- Bind services to **private IPs** where possible.
- Use **TLS** for PostgreSQL in production (menu option 17 for self-signed).
- Consider **etcd peer/client TLS** for the etcd cluster.
- **Patroni config** (`/etc/patroni/patroni.yml`) is written with mode 0600; it contains passwords.

---

## Support

For product support, contact your vendor or refer to your organization’s support process. Ensure you provide:

- Output of **Validate System Requirements** (menu 1).
- Relevant lines from `/var/log/pg_ha_setup.log`.
- OS and version (`cat /etc/os-release`).
